import html
from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import PaymentOrder, Tariff, User
from app.services.billing import credit_words, wallet_balance

router = Router(name="payments")


class PaymentFlow(StatesGroup):
    waiting_receipt = State()


def package_keyboard(tariffs: list[Tariff]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{tariff.name} — {tariff.amount_uzs:,} so‘m".replace(",", " "),
                callback_data=f"pay:package:{tariff.code}",
            )
        ]
        for tariff in tariffs
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash", callback_data=f"pay:approve:{order_id}"
                ),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"pay:reject:{order_id}"),
            ]
        ]
    )


@router.message(F.text == "💳 To‘lov qilish")
async def start_payment(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    await state.clear()
    if not settings.payment_ready:
        await message.answer(
            "⚠️ To‘lov rekvizitlari hozircha sozlanmagan. Administratorga murojaat qiling."
        )
        return
    async with session_maker() as session:
        tariffs = (
            await session.scalars(
                select(Tariff)
                .where(Tariff.is_active.is_(True))
                .order_by(Tariff.sort_order, Tariff.words)
            )
        ).all()
    if not tariffs:
        await message.answer("⚠️ Faol to‘lov paketi topilmadi. Administratorga murojaat qiling.")
        return
    await message.answer(
        "💳 <b>To‘lov paketini tanlang</b>\n\n"
        "Bank tanlash talab qilinmaydi. Paketni bossangiz, to‘lov rekvizitlari "
        "darhol ochiladi.",
        reply_markup=package_keyboard(list(tariffs)),
    )


@router.callback_query(F.data.startswith("pay:package:"))
async def choose_package(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if callback.from_user is None or callback.data is None:
        return
    code = callback.data.rsplit(":", 1)[-1]
    async with session_maker() as session:
        package = await session.scalar(
            select(Tariff).where(Tariff.code == code, Tariff.is_active.is_(True))
        )
        if package is None:
            await callback.answer("Paket topilmadi yoki o‘chirilgan.", show_alert=True)
            return
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if user is None:
            await callback.answer("Avval /start buyrug‘ini bosing.", show_alert=True)
            return
        abandoned = (
            await session.scalars(
                select(PaymentOrder)
                .where(PaymentOrder.user_id == user.id)
                .where(PaymentOrder.status == "awaiting_receipt")
            )
        ).all()
        for previous in abandoned:
            previous.status = "cancelled"
        open_orders = await session.scalar(
            select(func.count(PaymentOrder.id))
            .where(PaymentOrder.user_id == user.id)
            .where(PaymentOrder.status == "pending")
        )
        if int(open_orders or 0) >= 3:
            await callback.answer(
                "Avval yuborilgan to‘lovlaringiz ko‘rib chiqilishini kuting.", show_alert=True
            )
            return
        order = PaymentOrder(
            user_id=user.id,
            package_code=package.code,
            package_name=package.name,
            words=package.words,
            amount_uzs=package.amount_uzs,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
    await state.set_state(PaymentFlow.waiting_receipt)
    await state.update_data(payment_order_id=order.id)
    amount = f"{package.amount_uzs:,}".replace(",", " ")
    await callback.message.edit_text(
        "💳 <b>To‘lov ma’lumotlari</b>\n\n"
        f"📦 Paket: <b>{package.name}</b>\n"
        f"💵 Summa: <b>{amount} so‘m</b>\n"
        f"💳 Karta: <code>{html.escape(settings.payment_card_number)}</code>\n"
        f"👤 Qabul qiluvchi: <b>{html.escape(settings.payment_card_owner)}</b>\n\n"
        "To‘lovni amalga oshiring va <b>chek rasmini shu chatga yuboring</b>. "
        "Rasm aniq va summa ko‘rinadigan bo‘lsin."
    )
    await callback.answer()


@router.message(PaymentFlow.waiting_receipt, F.photo | F.document)
async def receive_receipt(
    message: Message,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    order_id = int(data.get("payment_order_id") or 0)
    if not order_id:
        await state.clear()
        await message.answer("To‘lov buyurtmasi topilmadi. Qaytadan urinib ko‘ring.")
        return
    if message.photo:
        receipt_file_id = message.photo[-1].file_id
        receipt_kind = "photo"
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        receipt_file_id = message.document.file_id
        receipt_kind = "document"
    else:
        await message.answer("❌ Chekni JPG yoki PNG rasm ko‘rinishida yuboring.")
        return
    async with session_maker() as session:
        row = (
            await session.execute(
                select(PaymentOrder, User)
                .join(User, User.id == PaymentOrder.user_id)
                .where(PaymentOrder.id == order_id)
            )
        ).one_or_none()
        if row is None or row.PaymentOrder.status != "awaiting_receipt":
            await state.clear()
            await message.answer("Bu to‘lov buyurtmasi yopilgan yoki topilmadi.")
            return
        order, user = row
        order.receipt_file_id = receipt_file_id
        order.receipt_kind = receipt_kind
        order.status = "pending"
        order.receipt_uploaded_at = datetime.now(UTC)
        await session.commit()
        username = f"@{user.username}" if user.username else "username yo‘q"
        caption = (
            f"🧾 <b>Yangi to‘lov cheki #{order.id}</b>\n\n"
            f"👤 {html.escape(user.first_name)} · {html.escape(username)}\n"
            f"🆔 <code>{user.telegram_id}</code>\n"
            f"📦 {html.escape(order.package_name)}\n"
            f"💵 {order.amount_uzs:,} so‘m".replace(",", " ")
        )
    for admin_id in settings.admin_id_set:
        try:
            if receipt_kind == "photo":
                await bot.send_photo(
                    admin_id,
                    receipt_file_id,
                    caption=caption,
                    reply_markup=review_keyboard(order_id),
                )
            else:
                await bot.send_document(
                    admin_id,
                    receipt_file_id,
                    caption=caption,
                    reply_markup=review_keyboard(order_id),
                )
        except Exception:
            continue
    await state.clear()
    await message.answer(
        "✅ Chek qabul qilindi. Administrator tekshirganidan keyin natija shu yerga yuboriladi."
    )


@router.message(PaymentFlow.waiting_receipt)
async def require_receipt_image(message: Message) -> None:
    await message.answer("Chekni JPG yoki PNG rasm ko‘rinishida yuboring.")


@router.callback_query(F.data.startswith("pay:approve:"))
async def approve_payment(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if callback.from_user.id not in settings.admin_id_set or callback.data is None:
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    order_id = int(callback.data.rsplit(":", 1)[-1])
    async with session_maker() as session:
        row = (
            await session.execute(
                select(PaymentOrder, User)
                .join(User, User.id == PaymentOrder.user_id)
                .where(PaymentOrder.id == order_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            await callback.answer("To‘lov topilmadi.", show_alert=True)
            return
        order, user = row
        if order.status != "pending":
            await callback.answer("Bu to‘lov avval ko‘rib chiqilgan.", show_alert=True)
            return
        _, balance = await credit_words(
            session,
            user_id=user.id,
            words=order.words,
            reference=f"payment:{order.id}",
            note=f"To‘lov #{order.id} tasdiqlandi",
        )
        order.status = "approved"
        order.reviewed_by_telegram_id = callback.from_user.id
        order.reviewed_at = datetime.now(UTC)
        await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(f"✅ To‘lov #{order_id} tasdiqlandi.")
    await bot.send_message(
        user.telegram_id,
        f"✅ <b>To‘lovingiz tasdiqlandi</b>\n\n"
        f"Balansga {order.words:,} so‘z qo‘shildi.\n"
        f"Joriy balans: <b>{balance:,} so‘z</b>".replace(",", " "),
    )
    await callback.answer("Tasdiqlandi")


@router.callback_query(F.data.startswith("pay:reject:"))
async def reject_payment(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if callback.from_user.id not in settings.admin_id_set or callback.data is None:
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    order_id = int(callback.data.rsplit(":", 1)[-1])
    async with session_maker() as session:
        row = (
            await session.execute(
                select(PaymentOrder, User)
                .join(User, User.id == PaymentOrder.user_id)
                .where(PaymentOrder.id == order_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None or row.PaymentOrder.status != "pending":
            await callback.answer("Bu to‘lov avval ko‘rib chiqilgan.", show_alert=True)
            return
        order, user = row
        order.status = "rejected"
        order.rejection_reason = "Chek ma’lumotlari tasdiqlanmadi"
        order.reviewed_by_telegram_id = callback.from_user.id
        order.reviewed_at = datetime.now(UTC)
        await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(f"❌ To‘lov #{order_id} rad etildi.")
    await bot.send_message(
        user.telegram_id,
        "❌ <b>To‘lov cheki tasdiqlanmadi.</b>\n\n"
        "Chekdagi summa yoki ma’lumotlarni tekshirib, qaytadan yuboring.",
    )
    await callback.answer("Rad etildi")


@router.message(F.text == "💰 Balansim")
async def show_balance(
    message: Message, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is None:
        return
    async with session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        balance = await wallet_balance(session, user.id) if user else 0
    await message.answer(
        f"💰 Joriy balansingiz: <b>{balance:,} so‘z</b>".replace(",", " ")
    )
