import math
from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import FeedbackMessage, User

router = Router(name="feedback")
MAX_FEEDBACK_CHARS = 4000


class FeedbackStates(StatesGroup):
    waiting_for_message = State()


async def _prompt(message: Message, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.waiting_for_message)
    await message.answer(
        "💬 Muammo yoki taklifingizni bitta xabar ko‘rinishida yozing.\n\n"
        "Masalan: botdagi xato, hisobotdagi kamchilik yoki yangi funksiya taklifi.\n"
        "Bekor qilish uchun /cancel yuboring."
    )


@router.message(Command("feedback"))
async def feedback_command(message: Message, state: FSMContext) -> None:
    await _prompt(message, state)


@router.message(F.text == "💬 Muammo va takliflar")
async def feedback_button(message: Message, state: FSMContext) -> None:
    await _prompt(message, state)


@router.message(FeedbackStates.waiting_for_message, Command("cancel"))
async def feedback_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Xabar yuborish bekor qilindi.")


@router.message(FeedbackStates.waiting_for_message, F.text)
async def feedback_message(
    message: Message,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if message.from_user is None or not message.text:
        return

    text = message.text.strip()
    if not text:
        await message.answer("Xabar bo‘sh bo‘lmasligi kerak. Qaytadan yozing.")
        return
    if len(text) > MAX_FEEDBACK_CHARS:
        await message.answer(
            f"Xabar juda uzun. Eng ko‘pi bilan {MAX_FEEDBACK_CHARS} ta belgi yuboring."
        )
        return

    async with session_maker() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if user is None:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or "",
                last_name=message.from_user.last_name,
            )
            session.add(user)
            await session.flush()

        latest = await session.scalar(
            select(FeedbackMessage)
            .where(FeedbackMessage.user_id == user.id)
            .order_by(FeedbackMessage.created_at.desc())
            .limit(1)
        )
        now = datetime.now(UTC)
        if latest is not None and latest.created_at is not None:
            created_at = latest.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            remaining_seconds = settings.feedback_cooldown_minutes * 60 - int(
                (now - created_at).total_seconds()
            )
            if remaining_seconds > 0:
                remaining_minutes = max(1, math.ceil(remaining_seconds / 60))
                await state.clear()
                await message.answer(
                    "⏳ Xabar yuborish limiti tugamadi. "
                    f"Yangi xabarni taxminan {remaining_minutes} daqiqadan keyin yuboring."
                )
                return

        feedback = FeedbackMessage(
            user_id=user.id,
            kind="problem_or_suggestion",
            message=text,
            status="new",
        )
        session.add(feedback)
        await session.commit()
        feedback_id = feedback.id
        display_name = " ".join(
            part for part in (user.first_name, user.last_name or "") if part
        ).strip() or "Noma’lum foydalanuvchi"
        username = f"@{user.username}" if user.username else "username yo‘q"
        telegram_id = user.telegram_id

    await state.clear()
    await message.answer(
        "✅ Xabaringiz administratorga yuborildi. Rahmat!\n"
        f"Keyingi xabarni {settings.feedback_cooldown_minutes} daqiqadan keyin yuborishingiz mumkin."
    )

    admin_text = (
        "🆕 <b>Yangi muammo yoki taklif</b>\n\n"
        f"🆔 Xabar ID: <code>#{feedback_id}</code>\n"
        f"👤 Foydalanuvchi: <b>{display_name}</b>\n"
        f"🔗 Username: {username}\n"
        f"🆔 Telegram ID: <code>{telegram_id}</code>\n\n"
        f"📝 {text}"
    )
    for admin_id in settings.admin_id_set:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            # The message remains visible in the web-admin panel even if a
            # Telegram notification cannot be delivered.
            continue
