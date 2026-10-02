# ruff: noqa: E501, E701, E702
import asyncio
import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import Bot
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.admin.security import (
    COOKIE_NAME,
    ROLE_LABELS,
    AdminIdentity,
    authenticate,
    create_session,
    hash_password,
    parse_form,
    require_admin,
    verify_csrf,
)
from app.admin.ui import badge, csrf_field, flash, login_page, number, page, pagination
from app.config import Settings
from app.models import (
    AdminAccount,
    AdminAudit,
    BroadcastLog,
    Certificate,
    ExternalScan,
    FeedbackMessage,
    PaymentOrder,
    Submission,
    Tariff,
    User,
    UserControl,
    Wallet,
    WalletTransaction,
)
from app.services.billing import credit_words, debit_words, wallet_balance
from app.services.scan_manager import QuetextScanManager

PER_PAGE = 30


def _go(path: str, message: str = "", kind: str = "ok") -> RedirectResponse:
    suffix = ""
    if message:
        from urllib.parse import urlencode

        suffix = "?" + urlencode({"message": message, "kind": kind})
    return RedirectResponse(path + suffix, status_code=303)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",", 1)[0].strip() if forwarded else request.client.host if request.client else "")[:80]


async def _audit(
    session: AsyncSession,
    request: Request,
    identity: AdminIdentity,
    action: str,
    target_type: str = "",
    target_id: str = "",
    details: str = "",
) -> None:
    session.add(
        AdminAudit(
            admin_username=identity.username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            ip_address=_client_ip(request),
        )
    )


def _admin(request: Request, settings: Settings, permission: str | None = None) -> AdminIdentity:
    return require_admin(request, settings, permission)


def _message(request: Request) -> str:
    return flash(request.query_params.get("message", ""), request.query_params.get("kind", "ok"))


def _csv_response(filename: str, rows: list[list[object]]) -> Response:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerows(rows)
    data = "\ufeff" + stream.getvalue()
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def build_admin_router(
    *,
    settings: Settings,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot | None = None,
    scan_manager: QuetextScanManager | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> Response:
        if settings.admin_web_ready and request.cookies.get(COOKIE_NAME):
            try:
                _admin(request, settings)
                return RedirectResponse("/admin/dashboard", status_code=303)
            except HTTPException:
                pass
        error = "" if settings.admin_web_ready else "ADMIN_WEB_PASSWORD va ADMIN_WEB_SECRET sozlanmagan."
        return HTMLResponse(login_page(error))

    @router.post("/admin/login")
    async def login_submit(request: Request) -> Response:
        if not settings.admin_web_ready:
            return HTMLResponse(login_page("Web-admin sozlanmagan."), status_code=503)
        form = await parse_form(request)
        async with session_maker() as session:
            identity = await authenticate(
                session,
                username=form.get("username", "").strip(),
                password=form.get("password", ""),
                settings=settings,
            )
            if identity is None:
                return HTMLResponse(login_page("Login yoki parol noto‘g‘ri."), status_code=401)
            await _audit(session, request, identity, "login")
            await session.commit()
        response = RedirectResponse("/admin/dashboard", status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            create_session(identity, settings),
            max_age=settings.admin_session_hours * 3600,
            httponly=True,
            secure=settings.verification_base_url.startswith("https://"),
            samesite="lax",
            path="/admin",
        )
        return response

    @router.post("/admin/logout")
    async def logout(request: Request) -> RedirectResponse:
        identity = _admin(request, settings)
        form = await parse_form(request)
        verify_csrf(identity, form)
        async with session_maker() as session:
            await _audit(session, request, identity, "logout")
            await session.commit()
        response = RedirectResponse("/admin/login", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/admin")
        return response

    @router.get("/admin")
    async def admin_root(request: Request) -> RedirectResponse:
        try:
            _admin(request, settings)
        except HTTPException:
            return RedirectResponse("/admin/login", status_code=303)
        return RedirectResponse("/admin/dashboard", status_code=303)

    @router.get("/admin/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        identity = _admin(request, settings, "dashboard")
        today = datetime.now(UTC) - timedelta(hours=24)
        async with session_maker() as session:
            users = await session.scalar(select(func.count(User.id))) or 0
            scans = await session.scalar(select(func.count(Submission.id))) or 0
            scans_today = await session.scalar(select(func.count(Submission.id)).where(Submission.created_at >= today)) or 0
            pending = await session.scalar(select(func.count(PaymentOrder.id)).where(PaymentOrder.status == "pending")) or 0
            revenue = await session.scalar(select(func.sum(PaymentOrder.amount_uzs)).where(PaymentOrder.status == "approved")) or 0
            words = await session.scalar(select(func.sum(Wallet.balance_words))) or 0
            failures = await session.scalar(select(func.count(ExternalScan.id)).where(ExternalScan.status == "failed")) or 0
            certificates = await session.scalar(select(func.count(Certificate.id)).where(Certificate.status == "active")) or 0
            recent_payments = (
                await session.execute(
                    select(PaymentOrder, User)
                    .join(User, User.id == PaymentOrder.user_id)
                    .order_by(PaymentOrder.created_at.desc())
                    .limit(8)
                )
            ).all()
            recent_scans = (
                await session.execute(
                    select(Submission, ExternalScan, User)
                    .join(User, User.id == Submission.user_id)
                    .outerjoin(ExternalScan, ExternalScan.submission_id == Submission.id)
                    .order_by(Submission.created_at.desc())
                    .limit(8)
                )
            ).all()
        payment_rows = "".join(
            f"<tr><td>#{order.id}</td><td>{escape(user.first_name or str(user.telegram_id))}</td><td>{escape(order.package_name)}</td><td>{number(order.amount_uzs)} so‘m</td><td>{badge(order.status)}</td></tr>"
            for order, user in recent_payments
        ) or '<tr><td colspan="5" class="empty">To‘lovlar yo‘q</td></tr>'
        scan_rows = "".join(
            f"<tr><td>{escape(item.filename)}</td><td>{escape(user.first_name or str(user.telegram_id))}</td><td>{number(item.word_count)}</td><td>{badge(scan.status if scan else 'unknown')}</td></tr>"
            for item, scan, user in recent_scans
        ) or '<tr><td colspan="4" class="empty">Tekshiruvlar yo‘q</td></tr>'
        body = _message(request) + f"""
        <section class="cards">
          <div class="card metric"><small>Foydalanuvchilar</small><b>{number(users)}</b></div>
          <div class="card metric"><small>Jami tekshiruv</small><b>{number(scans)}</b><span class="muted">24 soatda: {number(scans_today)}</span></div>
          <div class="card metric"><small>Tasdiqlangan tushum</small><b>{number(revenue)}</b><span class="muted">so‘m</span></div>
          <div class="card metric"><small>Kutilayotgan cheklar</small><b>{number(pending)}</b></div>
          <div class="card metric"><small>Jami faol balans</small><b>{number(words)}</b><span class="muted">so‘z</span></div>
          <div class="card metric"><small>Xatoli tekshiruvlar</small><b>{number(failures)}</b></div>
          <div class="card metric"><small>Faol sertifikatlar</small><b>{number(certificates)}</b></div>
          <div class="card metric"><small>Tizim</small><b style="font-size:18px">Ishlamoqda</b><span class="muted">Quetext + PostgreSQL</span></div>
        </section>
        <section class="grid2"><div class="card"><h2>Oxirgi to‘lovlar</h2><div class="table-wrap"><table><thead><tr><th>ID</th><th>Foydalanuvchi</th><th>Paket</th><th>Summa</th><th>Holat</th></tr></thead><tbody>{payment_rows}</tbody></table></div></div>
        <div class="card"><h2>Oxirgi tekshiruvlar</h2><div class="table-wrap"><table><thead><tr><th>Hujjat</th><th>Foydalanuvchi</th><th>So‘z</th><th>Holat</th></tr></thead><tbody>{scan_rows}</tbody></table></div></div></section>"""
        return HTMLResponse(page(title="Dashboard", subtitle="Asosiy ko‘rsatkichlar va tezkor nazorat", body=body, identity=identity, active="dashboard"))

    @router.get("/admin/users", response_class=HTMLResponse)
    async def users_page(request: Request, q: str = "", page_no: int = Query(1, alias="page", ge=1)) -> HTMLResponse:
        identity = _admin(request, settings, "users")
        conditions = []
        if q.strip():
            term = f"%{q.strip()}%"
            conditions.append(or_(User.first_name.ilike(term), User.last_name.ilike(term), User.username.ilike(term), cast(User.telegram_id, String).ilike(term)))
        async with session_maker() as session:
            total = await session.scalar(select(func.count(User.id)).where(*conditions)) or 0
            rows = (
                await session.execute(
                    select(User, Wallet, UserControl, func.count(Submission.id))
                    .outerjoin(Wallet, Wallet.user_id == User.id)
                    .outerjoin(UserControl, UserControl.user_id == User.id)
                    .outerjoin(Submission, Submission.user_id == User.id)
                    .where(*conditions)
                    .group_by(User.id, Wallet.id, UserControl.id)
                    .order_by(User.created_at.desc())
                    .offset((page_no - 1) * PER_PAGE)
                    .limit(PER_PAGE)
                )
            ).all()
        user_row_parts = []
        for user, wallet, control, count in rows:
            state_html = (
                '<span class="badge bad">Bloklangan</span>'
                if control and control.is_blocked
                else '<span class="badge ok">Faol</span>'
            )
            full_name = (user.first_name + " " + (user.last_name or "")).strip() or "Nomsiz"
            username = "@" + user.username if user.username else "username yo‘q"
            user_row_parts.append(
                f"<tr><td><a href='/admin/users/{user.id}'><b>{escape(full_name)}</b></a>"
                f"<br><span class='muted'>{escape(username)}</span></td>"
                f"<td><code>{user.telegram_id}</code></td>"
                f"<td>{number(wallet.balance_words if wallet else 0)}</td><td>{count}</td>"
                f"<td>{state_html}</td><td><a class='btn small secondary' "
                f"href='/admin/users/{user.id}'>Ochish</a></td></tr>"
            )
        table_rows = "".join(user_row_parts) or (
            '<tr><td colspan="6" class="empty">Foydalanuvchi topilmadi</td></tr>'
        )
        body = _message(request) + f"<div class='card'><form class='toolbar' method='get'><input name='q' value='{escape(q)}' placeholder='Ism, username yoki Telegram ID'><button>Qidirish</button><a class='btn secondary' href='/admin/users'>Tozalash</a></form><div class='table-wrap'><table><thead><tr><th>Foydalanuvchi</th><th>Telegram ID</th><th>Balans</th><th>Tekshiruv</th><th>Holat</th><th></th></tr></thead><tbody>{table_rows}</tbody></table></div>{pagination('/admin/users', page_no, total, PER_PAGE, q=q)}</div>"
        return HTMLResponse(page(title="Foydalanuvchilar", subtitle=f"Jami {number(total)} ta foydalanuvchi", body=body, identity=identity, active="users"))

    @router.get("/admin/users/{user_id}", response_class=HTMLResponse)
    async def user_detail(user_id: int, request: Request) -> HTMLResponse:
        identity = _admin(request, settings, "users")
        async with session_maker() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise HTTPException(404, "Foydalanuvchi topilmadi.")
            balance = await wallet_balance(session, user.id)
            control = await session.scalar(select(UserControl).where(UserControl.user_id == user.id))
            transactions = (await session.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id).order_by(WalletTransaction.created_at.desc()).limit(15))).all()
            payments = (await session.scalars(select(PaymentOrder).where(PaymentOrder.user_id == user.id).order_by(PaymentOrder.created_at.desc()).limit(10))).all()
        tx_rows = "".join(f"<tr><td>{tx.created_at:%d.%m.%Y %H:%M}</td><td>{escape(tx.kind)}</td><td>{'+' if tx.amount_words > 0 else ''}{number(tx.amount_words)}</td><td>{number(tx.balance_after)}</td><td>{escape(tx.note)}</td></tr>" for tx in transactions) or '<tr><td colspan="5" class="empty">Harakatlar yo‘q</td></tr>'
        pay_rows = "".join(f"<tr><td>#{p.id}</td><td>{escape(p.package_name)}</td><td>{number(p.amount_uzs)} so‘m</td><td>{badge(p.status)}</td></tr>" for p in payments) or '<tr><td colspan="4" class="empty">To‘lovlar yo‘q</td></tr>'
        balance_panel = (
            f'<div class="card"><h2>Balansni o‘zgartirish</h2><form method="post" '
            f'action="/admin/users/{user.id}/balance" class="form-grid">{csrf_field(identity)}'
            '<label>Miqdor (ayirish uchun minus)<input type="number" name="amount" '
            'required placeholder="Masalan: 10000 yoki -5000"></label><label>Sabab'
            '<input name="reason" required minlength="3"></label><label class="wide"><span>'
            '<input class="confirm" type="checkbox" name="confirm" value="yes" required> '
            'Amalni tasdiqlayman</span></label><div><button>Balansni saqlash</button></div>'
            '</form></div>'
            if identity.can("balance")
            else '<div class="card"><h2>Balans</h2><p class="muted">Faqat ko‘rish rejimi.</p></div>'
        )
        control_panel = (
            f'<div class="card"><h2>Foydalanuvchi nazorati</h2><p class="muted">'
            f'Bloklangan foydalanuvchi yangi hujjat tekshira olmaydi.</p><form method="post" '
            f'action="/admin/users/{user.id}/block">{csrf_field(identity)}<input type="hidden" '
            f'name="block" value="{"0" if control and control.is_blocked else "1"}"><label>Sabab'
            f'<input name="reason" value="{escape(control.reason if control else "")}" required>'
            f'</label><br><button class="{"secondary" if control and control.is_blocked else "danger"}">'
            f'{"Blokdan chiqarish" if control and control.is_blocked else "Bloklash"}</button></form></div>'
            if identity.can("user_manage")
            else '<div class="card"><h2>Foydalanuvchi nazorati</h2><p class="muted">Faqat ko‘rish rejimi.</p></div>'
        )
        body = _message(request) + f"""
        <div class="cards"><div class="card metric"><small>Ism</small><b style="font-size:18px">{escape((user.first_name + ' ' + (user.last_name or '')).strip())}</b></div><div class="card metric"><small>Telegram ID</small><b style="font-size:18px">{user.telegram_id}</b></div><div class="card metric"><small>Balans</small><b>{number(balance)}</b><span class="muted">so‘z</span></div><div class="card metric"><small>Holat</small><b style="font-size:18px">{'Bloklangan' if control and control.is_blocked else 'Faol'}</b></div></div>
        <section class="grid2">{balance_panel}{control_panel}</section>
        <br><section class="card"><h2>Balans tarixi</h2><div class="table-wrap"><table><thead><tr><th>Vaqt</th><th>Turi</th><th>Miqdor</th><th>Qoldiq</th><th>Izoh</th></tr></thead><tbody>{tx_rows}</tbody></table></div></section><br><section class="card"><h2>To‘lovlar</h2><div class="table-wrap"><table><thead><tr><th>ID</th><th>Paket</th><th>Summa</th><th>Holat</th></tr></thead><tbody>{pay_rows}</tbody></table></div></section>"""
        return HTMLResponse(page(title="Foydalanuvchi", subtitle=escape('@' + user.username if user.username else str(user.telegram_id)), body=body, identity=identity, active="users"))

    @router.post("/admin/users/{user_id}/balance")
    async def change_balance(user_id: int, request: Request) -> RedirectResponse:
        identity = _admin(request, settings, "balance")
        form = await parse_form(request); verify_csrf(identity, form)
        if form.get("confirm") != "yes":
            return _go(f"/admin/users/{user_id}", "Tasdiqlash belgilanmagan.", "bad")
        try:
            amount = int(form.get("amount", "0"))
        except ValueError:
            amount = 0
        reason = form.get("reason", "").strip()
        if amount == 0 or len(reason) < 3:
            return _go(f"/admin/users/{user_id}", "Miqdor yoki sabab noto‘g‘ri.", "bad")
        async with session_maker() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise HTTPException(404, "Foydalanuvchi topilmadi.")
            reference = f"admin:{identity.username}:{uuid.uuid4().hex}"
            if amount > 0:
                _, balance = await credit_words(session, user_id=user.id, words=amount, reference=reference, note=reason)
            else:
                ok, balance = await debit_words(session, user_id=user.id, words=abs(amount), reference=reference, note=reason)
                if not ok:
                    return _go(f"/admin/users/{user_id}", "Balansda yetarli so‘z yo‘q.", "bad")
            await _audit(session, request, identity, "balance_change", "user", str(user_id), f"amount={amount}; balance={balance}; reason={reason}")
            await session.commit()
        if bot:
            try:
                await bot.send_message(user.telegram_id, f"💰 Balansingiz administrator tomonidan o‘zgartirildi.\nMiqdor: <b>{amount:+,} so‘z</b>\nYangi balans: <b>{balance:,} so‘z</b>\nSabab: {escape(reason)}".replace(",", " "))
            except Exception:
                pass
        return _go(f"/admin/users/{user_id}", "Balans muvaffaqiyatli o‘zgartirildi.")

    @router.post("/admin/users/{user_id}/block")
    async def block_user(user_id: int, request: Request) -> RedirectResponse:
        identity = _admin(request, settings, "user_manage")
        form = await parse_form(request); verify_csrf(identity, form)
        blocked = form.get("block") == "1"; reason = form.get("reason", "").strip()
        async with session_maker() as session:
            control = await session.scalar(select(UserControl).where(UserControl.user_id == user_id).with_for_update())
            if control is None:
                control = UserControl(user_id=user_id); session.add(control)
            control.is_blocked = blocked; control.reason = reason
            await _audit(session, request, identity, "user_block" if blocked else "user_unblock", "user", str(user_id), reason)
            await session.commit()
        return _go(f"/admin/users/{user_id}", "Foydalanuvchi holati yangilandi.")

    @router.get("/admin/payments", response_class=HTMLResponse)
    async def payments_page(request: Request, status: str = "", q: str = "", page_no: int = Query(1, alias="page", ge=1)) -> HTMLResponse:
        identity = _admin(request, settings, "payments")
        conditions = []
        if status: conditions.append(PaymentOrder.status == status)
        if q.strip():
            term = f"%{q.strip()}%"; conditions.append(or_(PaymentOrder.package_name.ilike(term), cast(PaymentOrder.id, String).ilike(term), User.first_name.ilike(term), User.username.ilike(term), cast(User.telegram_id, String).ilike(term)))
        async with session_maker() as session:
            total = await session.scalar(select(func.count(PaymentOrder.id)).join(User).where(*conditions)) or 0
            rows = (await session.execute(select(PaymentOrder, User).join(User).where(*conditions).order_by(PaymentOrder.created_at.desc()).offset((page_no - 1) * PER_PAGE).limit(PER_PAGE))).all()
        table_rows = "".join(f"<tr><td><a href='/admin/payments/{order.id}'><b>#{order.id}</b></a></td><td>{escape(user.first_name)}<br><span class='muted'>{user.telegram_id}</span></td><td>{escape(order.package_name)}</td><td>{number(order.amount_uzs)} so‘m</td><td>{badge(order.status)}</td><td>{order.created_at:%d.%m.%Y %H:%M}</td><td><a class='btn small secondary' href='/admin/payments/{order.id}'>Ko‘rish</a></td></tr>" for order, user in rows) or '<tr><td colspan="7" class="empty">To‘lov topilmadi</td></tr>'
        options = "".join(f"<option value='{s}' {'selected' if status == s else ''}>{escape(s)}</option>" for s in ["pending", "approved", "rejected", "awaiting_receipt", "cancelled"])
        body = _message(request) + f"<div class='card'><form class='toolbar' method='get'><input name='q' value='{escape(q)}' placeholder='ID, ism, username'><select name='status'><option value=''>Barcha holatlar</option>{options}</select><button>Filtrlash</button><a class='btn secondary' href='/admin/payments'>Tozalash</a></form><div class='table-wrap'><table><thead><tr><th>ID</th><th>Foydalanuvchi</th><th>Paket</th><th>Summa</th><th>Holat</th><th>Vaqt</th><th></th></tr></thead><tbody>{table_rows}</tbody></table></div>{pagination('/admin/payments', page_no, total, PER_PAGE, q=q, status=status)}</div>"
        return HTMLResponse(page(title="To‘lovlar", subtitle=f"Jami {number(total)} ta yozuv", body=body, identity=identity, active="payments"))

    @router.get("/admin/payments/{order_id}", response_class=HTMLResponse)
    async def payment_detail(order_id: int, request: Request) -> HTMLResponse:
        identity = _admin(request, settings, "payments")
        async with session_maker() as session:
            row = (await session.execute(select(PaymentOrder, User).join(User).where(PaymentOrder.id == order_id))).one_or_none()
        if row is None: raise HTTPException(404, "To‘lov topilmadi.")
        order, user = row
        receipt = f"<img class='receipt' src='/admin/payments/{order.id}/receipt' alt='Chek'>" if order.receipt_file_id else "<div class='empty'>Chek yuklanmagan</div>"
        actions = ""
        if order.status == "pending" and identity.can("payment_manage"):
            actions = f"<div class='actions'><form method='post' action='/admin/payments/{order.id}/approve'>{csrf_field(identity)}<label><span><input class='confirm' type='checkbox' name='confirm' value='yes' required> Tasdiqlash</span></label><button>Tasdiqlash</button></form><form method='post' action='/admin/payments/{order.id}/reject'>{csrf_field(identity)}<label>Rad etish sababi<input name='reason' required value='Chek ma’lumotlari tasdiqlanmadi'></label><button class='danger'>Rad etish</button></form></div>"
        body = _message(request) + f"<section class='grid2'><div class='card'><h2>To‘lov #{order.id}</h2><p><b>Foydalanuvchi:</b> <a href='/admin/users/{user.id}'>{escape(user.first_name)}</a> · {user.telegram_id}</p><p><b>Paket:</b> {escape(order.package_name)}</p><p><b>Summa:</b> {number(order.amount_uzs)} so‘m</p><p><b>Holat:</b> {badge(order.status)}</p><p><b>Yaratilgan:</b> {order.created_at:%d.%m.%Y %H:%M}</p>{actions}</div><div class='card'><h2>Chek rasmi</h2>{receipt}</div></section>"
        return HTMLResponse(page(title=f"To‘lov #{order.id}", subtitle="Chekni tekshirish va qaror qabul qilish", body=body, identity=identity, active="payments"))

    @router.get("/admin/payments/{order_id}/receipt")
    async def payment_receipt(order_id: int, request: Request) -> StreamingResponse:
        _admin(request, settings, "payments")
        if bot is None: raise HTTPException(503, "Telegram ulanishi mavjud emas.")
        async with session_maker() as session:
            order = await session.get(PaymentOrder, order_id)
        if order is None or not order.receipt_file_id: raise HTTPException(404, "Chek topilmadi.")
        target = io.BytesIO(); await bot.download(order.receipt_file_id, destination=target); target.seek(0)
        return StreamingResponse(target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})

    @router.post("/admin/payments/{order_id}/approve")
    async def payment_approve(order_id: int, request: Request) -> RedirectResponse:
        identity = _admin(request, settings, "payment_manage"); form = await parse_form(request); verify_csrf(identity, form)
        if form.get("confirm") != "yes": return _go(f"/admin/payments/{order_id}", "Tasdiqlash belgilanmagan.", "bad")
        async with session_maker() as session:
            row = (await session.execute(select(PaymentOrder, User).join(User).where(PaymentOrder.id == order_id).with_for_update())).one_or_none()
            if row is None: raise HTTPException(404, "To‘lov topilmadi.")
            order, user = row
            if order.status != "pending": return _go(f"/admin/payments/{order_id}", "To‘lov avval ko‘rib chiqilgan.", "bad")
            _, balance = await credit_words(session, user_id=user.id, words=order.words, reference=f"payment:{order.id}", note=f"Web-admin: {identity.username}")
            order.status = "approved"; order.reviewed_at = datetime.now(UTC)
            await _audit(session, request, identity, "payment_approve", "payment", str(order.id), f"words={order.words}; amount={order.amount_uzs}")
            await session.commit()
        if bot:
            try: await bot.send_message(user.telegram_id, f"✅ <b>To‘lovingiz tasdiqlandi</b>\nBalansga {number(order.words)} so‘z qo‘shildi.\nJoriy balans: <b>{number(balance)} so‘z</b>")
            except Exception: pass
        return _go(f"/admin/payments/{order_id}", "To‘lov tasdiqlandi.")

    @router.post("/admin/payments/{order_id}/reject")
    async def payment_reject(order_id: int, request: Request) -> RedirectResponse:
        identity = _admin(request, settings, "payment_manage"); form = await parse_form(request); verify_csrf(identity, form); reason = form.get("reason", "").strip()
        if not reason: return _go(f"/admin/payments/{order_id}", "Rad etish sababini yozing.", "bad")
        async with session_maker() as session:
            row = (await session.execute(select(PaymentOrder, User).join(User).where(PaymentOrder.id == order_id).with_for_update())).one_or_none()
            if row is None: raise HTTPException(404, "To‘lov topilmadi.")
            order, user = row
            if order.status != "pending": return _go(f"/admin/payments/{order_id}", "To‘lov avval ko‘rib chiqilgan.", "bad")
            order.status = "rejected"; order.rejection_reason = reason; order.reviewed_at = datetime.now(UTC)
            await _audit(session, request, identity, "payment_reject", "payment", str(order.id), reason); await session.commit()
        if bot:
            try: await bot.send_message(user.telegram_id, f"❌ <b>To‘lov cheki tasdiqlanmadi.</b>\nSabab: {escape(reason)}")
            except Exception: pass
        return _go(f"/admin/payments/{order_id}", "To‘lov rad etildi.")

    @router.get("/admin/tariffs", response_class=HTMLResponse)
    async def tariffs_page(request: Request) -> HTMLResponse:
        identity = _admin(request, settings)
        if not identity.can("*"): raise HTTPException(403, "Faqat bosh administrator uchun.")
        async with session_maker() as session:
            tariffs = (await session.scalars(select(Tariff).order_by(Tariff.sort_order, Tariff.words))).all()
        tariff_parts = []
        for tariff in tariffs:
            tariff_state = (
                '<span class="badge ok">Faol</span>'
                if tariff.is_active
                else '<span class="badge bad">O‘chiq</span>'
            )
            toggle_label = "O‘chirish" if tariff.is_active else "Yoqish"
            tariff_parts.append(
                f"<tr><td colspan='5'><form class='toolbar' method='post' "
                f"action='/admin/tariffs/{tariff.id}/update'>{csrf_field(identity)}"
                f"<input name='name' value='{escape(tariff.name)}' aria-label='Tarif nomi'>"
                f"<input type='number' name='words' value='{tariff.words}' aria-label='So‘zlar'>"
                f"<input type='number' name='amount' value='{tariff.amount_uzs}' aria-label='Narx'>"
                f"{tariff_state} "
                f"<button class='small'>Saqlash</button> <button class='small secondary' "
                f"name='toggle' value='1'>{toggle_label}</button></form></td></tr>"
            )
        rows = "".join(tariff_parts)
        body = _message(request) + f"<section class='card'><h2>Yangi tarif</h2><form method='post' action='/admin/tariffs/create' class='form-grid'>{csrf_field(identity)}<label>Nomi<input name='name' required placeholder='10 000 so‘z'></label><label>Kod<input name='code' required pattern='[a-zA-Z0-9_-]+'></label><label>So‘z miqdori<input type='number' name='words' min='100' required></label><label>Narxi, so‘m<input type='number' name='amount' min='1000' required></label><div><button>Tarif qo‘shish</button></div></form></section><br><section class='card'><h2>Tariflar</h2><div class='table-wrap'><table><thead><tr><th>Nomi</th><th>So‘z</th><th>Narx</th><th>Holat</th><th>Amal</th></tr></thead><tbody>{rows}</tbody></table></div></section>"
        return HTMLResponse(page(title="Tariflar", subtitle="Botdagi paketlar va narxlarni boshqarish", body=body, identity=identity, active="tariffs"))

    @router.post("/admin/tariffs/create")
    async def tariff_create(request: Request) -> RedirectResponse:
        identity = _admin(request, settings); form = await parse_form(request); verify_csrf(identity, form)
        if not identity.can("*"): raise HTTPException(403)
        try: words = int(form["words"]); amount = int(form["amount"])
        except (KeyError, ValueError): return _go("/admin/tariffs", "Qiymatlar noto‘g‘ri.", "bad")
        async with session_maker() as session:
            session.add(Tariff(code=form.get("code", "").strip(), name=form.get("name", "").strip(), words=words, amount_uzs=amount))
            await _audit(session, request, identity, "tariff_create", "tariff", form.get("code", ""), f"words={words}; amount={amount}")
            try: await session.commit()
            except Exception: await session.rollback(); return _go("/admin/tariffs", "Tarif kodi takrorlangan.", "bad")
        return _go("/admin/tariffs", "Tarif qo‘shildi.")

    @router.post("/admin/tariffs/{tariff_id}/update")
    async def tariff_update(tariff_id: int, request: Request) -> RedirectResponse:
        identity = _admin(request, settings); form = await parse_form(request); verify_csrf(identity, form)
        if not identity.can("*"): raise HTTPException(403)
        async with session_maker() as session:
            tariff = await session.get(Tariff, tariff_id)
            if tariff is None: raise HTTPException(404)
            if form.get("toggle") == "1": tariff.is_active = not tariff.is_active
            else:
                tariff.name = form.get("name", tariff.name).strip(); tariff.words = int(form.get("words", tariff.words)); tariff.amount_uzs = int(form.get("amount", tariff.amount_uzs))
            await _audit(session, request, identity, "tariff_update", "tariff", str(tariff_id), f"active={tariff.is_active}; words={tariff.words}; amount={tariff.amount_uzs}"); await session.commit()
        return _go("/admin/tariffs", "Tarif yangilandi.")

    @router.get("/admin/scans", response_class=HTMLResponse)
    async def scans_page(request: Request, status: str = "", q: str = "", page_no: int = Query(1, alias="page", ge=1)) -> HTMLResponse:
        identity = _admin(request, settings, "scans")
        conditions = []
        if status: conditions.append(ExternalScan.status == status)
        if q.strip():
            term = f"%{q.strip()}%"; conditions.append(or_(Submission.filename.ilike(term), ExternalScan.scan_id.ilike(term), User.first_name.ilike(term), cast(User.telegram_id, String).ilike(term)))
        async with session_maker() as session:
            base = select(Submission, ExternalScan, User).join(User).outerjoin(ExternalScan, ExternalScan.submission_id == Submission.id).where(*conditions)
            total = await session.scalar(select(func.count(Submission.id)).join(User).outerjoin(ExternalScan).where(*conditions)) or 0
            rows = (await session.execute(base.order_by(Submission.created_at.desc()).offset((page_no - 1) * PER_PAGE).limit(PER_PAGE))).all()
        scan_parts = []
        for item, scan, user in rows:
            retry = ""
            if scan and scan.status == "failed" and identity.can("scan_manage"):
                retry = (
                    f"<form class='inline' method='post' action='/admin/scans/{scan.scan_id}/retry'>"
                    f"{csrf_field(identity)}<button class='small secondary'>Qayta urinish</button></form>"
                )
            scan_parts.append(
                f"<tr><td>{escape(item.filename)}<br><span class='muted'>"
                f"{scan.scan_id[:12] if scan else ''}</span></td>"
                f"<td>{escape(user.first_name)}<br>{user.telegram_id}</td>"
                f"<td>{number(item.word_count)}</td><td>{badge(scan.status if scan else 'unknown')}</td>"
                f"<td>{item.originality_score:.2f}%</td><td>{item.created_at:%d.%m.%Y %H:%M}</td>"
                f"<td>{retry}</td></tr>"
            )
        table_rows = "".join(scan_parts) or (
            '<tr><td colspan="7" class="empty">Tekshiruv topilmadi</td></tr>'
        )
        options = "".join(f"<option value='{s}' {'selected' if status == s else ''}>{s}</option>" for s in ["pending", "completed", "failed"])
        body = _message(request) + f"<div class='card'><form class='toolbar' method='get'><input name='q' value='{escape(q)}' placeholder='Fayl, scan ID, foydalanuvchi'><select name='status'><option value=''>Barcha holatlar</option>{options}</select><button>Filtrlash</button><a class='btn secondary' href='/admin/scans'>Tozalash</a></form><div class='table-wrap'><table><thead><tr><th>Hujjat</th><th>Foydalanuvchi</th><th>So‘z</th><th>Holat</th><th>Originallik</th><th>Vaqt</th><th></th></tr></thead><tbody>{table_rows}</tbody></table></div>{pagination('/admin/scans', page_no, total, PER_PAGE, q=q, status=status)}</div>"
        return HTMLResponse(page(title="Tekshiruvlar", subtitle=f"Jami {number(total)} ta hujjat", body=body, identity=identity, active="scans"))

    @router.post("/admin/scans/{scan_id}/retry")
    async def retry_scan(scan_id: str, request: Request) -> RedirectResponse:
        identity = _admin(request, settings, "scan_manage"); form = await parse_form(request); verify_csrf(identity, form)
        async with session_maker() as session:
            scan = await session.scalar(select(ExternalScan).where(ExternalScan.scan_id == scan_id).with_for_update())
            if scan is None: raise HTTPException(404)
            scan.status = "pending"; scan.error_message = None; scan.completed_at = None; scan.notified_at = None
            await _audit(session, request, identity, "scan_retry", "scan", scan_id); await session.commit()
        if scan_manager: scan_manager.start(scan_id)
        return _go("/admin/scans", "Tekshiruv qayta navbatga qo‘yildi.")

    @router.get("/admin/certificates", response_class=HTMLResponse)
    async def certificates_page(request: Request, q: str = "", status: str = "", page_no: int = Query(1, alias="page", ge=1)) -> HTMLResponse:
        identity = _admin(request, settings, "certificates")
        conditions = []
        if status: conditions.append(Certificate.status == status)
        if q.strip():
            term = f"%{q.strip()}%"; conditions.append(or_(Certificate.certificate_number.ilike(term), Certificate.document_name.ilike(term), Certificate.recipient_name.ilike(term)))
        async with session_maker() as session:
            total = await session.scalar(select(func.count(Certificate.id)).where(*conditions)) or 0
            rows = (await session.scalars(select(Certificate).where(*conditions).order_by(Certificate.issued_at.desc()).offset((page_no - 1) * PER_PAGE).limit(PER_PAGE))).all()
        certificate_parts = []
        for certificate in rows:
            action = ""
            if identity.can("certificate_manage"):
                button_class = "danger" if certificate.status == "active" else "secondary"
                button_label = "Bekor qilish" if certificate.status == "active" else "Faollashtirish"
                action = (
                    f"<form class='inline' method='post' action='/admin/certificates/{certificate.id}/toggle'>"
                    f"{csrf_field(identity)}<button class='small {button_class}'>{button_label}</button></form>"
                )
            certificate_parts.append(
                f"<tr><td><code>{escape(certificate.certificate_number)}</code></td>"
                f"<td>{escape(certificate.document_name)}</td><td>{escape(certificate.recipient_name)}</td>"
                f"<td>{certificate.originality_score:.2f}%</td><td>{badge(certificate.status)}</td>"
                f"<td>{certificate.issued_at:%d.%m.%Y}</td><td>{action}</td></tr>"
            )
        table_rows = "".join(certificate_parts) or (
            '<tr><td colspan="7" class="empty">Sertifikat topilmadi</td></tr>'
        )
        body = _message(request) + f"<div class='card'><form class='toolbar' method='get'><input name='q' value='{escape(q)}' placeholder='Sertifikat ID yoki hujjat'><select name='status'><option value=''>Barcha holatlar</option><option value='active' {'selected' if status == 'active' else ''}>Faol</option><option value='revoked' {'selected' if status == 'revoked' else ''}>Bekor qilingan</option></select><button>Qidirish</button></form><div class='table-wrap'><table><thead><tr><th>ID</th><th>Hujjat</th><th>Qabul qiluvchi</th><th>Originallik</th><th>Holat</th><th>Sana</th><th></th></tr></thead><tbody>{table_rows}</tbody></table></div>{pagination('/admin/certificates', page_no, total, PER_PAGE, q=q, status=status)}</div>"
        return HTMLResponse(page(title="Sertifikatlar", subtitle=f"Jami {number(total)} ta sertifikat", body=body, identity=identity, active="certificates"))

    @router.post("/admin/certificates/{certificate_id}/toggle")
    async def toggle_certificate(certificate_id: int, request: Request) -> RedirectResponse:
        identity = _admin(request, settings, "certificate_manage"); form = await parse_form(request); verify_csrf(identity, form)
        async with session_maker() as session:
            certificate = await session.get(Certificate, certificate_id)
            if certificate is None: raise HTTPException(404)
            if certificate.status == "active": certificate.status = "revoked"; certificate.revoked_at = datetime.now(UTC)
            else: certificate.status = "active"; certificate.revoked_at = None
            await _audit(session, request, identity, "certificate_toggle", "certificate", str(certificate_id), certificate.status); await session.commit()
        return _go("/admin/certificates", "Sertifikat holati yangilandi.")

    @router.get("/admin/broadcast", response_class=HTMLResponse)
    async def broadcast_page(request: Request) -> HTMLResponse:
        identity = _admin(request, settings, "broadcast")
        body = _message(request) + f"<section class='grid2'><div class='card'><h2>Ommaviy xabar</h2><form method='post' action='/admin/broadcast/preview'>{csrf_field(identity)}<label>Auditoriya<select name='audience'><option value='all'>Barcha foydalanuvchilar</option><option value='active'>Bloklanmagan foydalanuvchilar</option></select></label><br><label>Xabar matni<textarea name='message' minlength='2' maxlength='4000' required placeholder='Xabar matnini yozing...'></textarea></label><br><button>Oldindan ko‘rish</button></form></div><div class='card'><h2>Xavfsiz yuborish</h2><p class='muted'>Xabar avval alohida sahifada ko‘rsatiladi. Faqat ikkinchi tasdiqdan keyin foydalanuvchilarga yuboriladi.</p></div></section>"
        return HTMLResponse(page(title="Xabar yuborish", subtitle="Auditoriyani tanlash, ko‘rib chiqish va tasdiqlash", body=body, identity=identity, active="broadcast"))

    @router.post("/admin/broadcast/preview", response_class=HTMLResponse)
    async def broadcast_preview(request: Request) -> HTMLResponse:
        identity = _admin(request, settings, "broadcast"); form = await parse_form(request); verify_csrf(identity, form)
        message = form.get("message", "").strip(); audience = form.get("audience", "all")
        if not message: raise HTTPException(400, "Xabar bo‘sh.")
        body = f"<section class='grid2'><div class='card'><h2>Oldindan ko‘rish</h2><div style='white-space:pre-wrap;line-height:1.55;padding:16px;background:#f8fafc;border-radius:12px'>{escape(message)}</div></div><div class='card'><h2>Tasdiqlash</h2><p>Auditoriya: <b>{'Barcha foydalanuvchilar' if audience == 'all' else 'Bloklanmagan foydalanuvchilar'}</b></p><form method='post' action='/admin/broadcast/send'>{csrf_field(identity)}<input type='hidden' name='audience' value='{escape(audience)}'><input type='hidden' name='message' value='{escape(message, quote=True)}'><label><span><input class='confirm' type='checkbox' name='confirm' value='yes' required> Xabarni yuborishni tasdiqlayman</span></label><br><button>Yuborish</button> <a class='btn secondary' href='/admin/broadcast'>Ortga</a></form></div></section>"
        return HTMLResponse(page(title="Xabarni tekshirish", subtitle="Yuborishdan oldingi yakuniy ko‘rinish", body=body, identity=identity, active="broadcast"))

    @router.post("/admin/broadcast/send")
    async def broadcast_send(request: Request) -> RedirectResponse:
        identity = _admin(request, settings, "broadcast"); form = await parse_form(request); verify_csrf(identity, form)
        if form.get("confirm") != "yes" or bot is None: return _go("/admin/broadcast", "Yuborish tasdiqlanmadi yoki bot ulanmagan.", "bad")
        message = form.get("message", "").strip(); audience = form.get("audience", "all")
        async with session_maker() as session:
            query = select(User.telegram_id)
            if audience == "active": query = query.outerjoin(UserControl, UserControl.user_id == User.id).where(or_(UserControl.id.is_(None), UserControl.is_blocked.is_(False)))
            recipients = list((await session.scalars(query)).all())
        sent = failed = 0
        for telegram_id in recipients:
            try: await bot.send_message(telegram_id, message); sent += 1
            except Exception: failed += 1
            await asyncio.sleep(0.035)
        async with session_maker() as session:
            session.add(BroadcastLog(admin_username=identity.username, message_text=message, audience=audience, total_count=len(recipients), sent_count=sent, failed_count=failed))
            await _audit(session, request, identity, "broadcast", "users", audience, f"total={len(recipients)}; sent={sent}; failed={failed}"); await session.commit()
        return _go("/admin/broadcast", f"Xabar yuborildi: {sent} ta. Xato: {failed} ta.")

    @router.get("/admin/feedback", response_class=HTMLResponse)
    async def feedback_page(
        request: Request,
        status: str = "",
        page_no: int = Query(1, alias="page", ge=1),
    ) -> HTMLResponse:
        identity = _admin(request, settings, "feedback")
        conditions = []
        if status:
            conditions.append(FeedbackMessage.status == status)
        async with session_maker() as session:
            total = await session.scalar(
                select(func.count(FeedbackMessage.id)).where(*conditions)
            ) or 0
            rows = (
                await session.execute(
                    select(FeedbackMessage, User)
                    .join(User, User.id == FeedbackMessage.user_id)
                    .where(*conditions)
                    .order_by(FeedbackMessage.created_at.desc())
                    .offset((page_no - 1) * PER_PAGE)
                    .limit(PER_PAGE)
                )
            ).all()
        feedback_rows = []
        for item, user in rows:
            display_name = " ".join(
                part for part in (user.first_name, user.last_name or "") if part
            ).strip() or "Noma’lum"
            next_status = "new" if item.status == "resolved" else "resolved"
            action_label = "Qayta ochish" if item.status == "resolved" else "Ko‘rib chiqildi"
            action_class = "secondary" if item.status == "resolved" else ""
            action = (
                f"<form class='inline' method='post' action='/admin/feedback/{item.id}/status'>"
                f"{csrf_field(identity)}<input type='hidden' name='status' value='{next_status}'>"
                f"<button class='small {action_class}'>{action_label}</button></form>"
            )
            feedback_rows.append(
                f"<tr><td><code>#{item.id}</code><br><span class='muted'>"
                f"{item.created_at:%d.%m.%Y %H:%M}</span></td>"
                f"<td><b>{escape(display_name)}</b><br><span class='muted'>"
                f"{user.telegram_id}</span></td>"
                f"<td>{badge(item.status)}</td>"
                f"<td><div style='white-space:pre-wrap;min-width:360px;max-width:680px'>"
                f"{escape(item.message)}</div></td><td>{action}</td></tr>"
            )
        table_rows = "".join(feedback_rows) or (
            '<tr><td colspan="5" class="empty">Hozircha muammo yoki takliflar yo‘q</td></tr>'
        )
        status_options = "".join(
            f"<option value='{value}' {'selected' if status == value else ''}>{label}</option>"
            for value, label in (
                ("", "Barcha xabarlar"),
                ("new", "Yangi"),
                ("resolved", "Ko‘rib chiqilgan"),
            )
        )
        body = (
            _message(request)
            + f"<div class='card'><form class='toolbar' method='get'>"
            f"<select name='status'>{status_options}</select><button>Filtrlash</button>"
            f"<a class='btn secondary' href='/admin/feedback'>Tozalash</a></form>"
            f"<div class='table-wrap'><table><thead><tr><th>ID / vaqt</th>"
            f"<th>Foydalanuvchi</th><th>Holat</th><th>Xabar</th><th>Amal</th></tr></thead>"
            f"<tbody>{table_rows}</tbody></table></div>"
            f"{pagination('/admin/feedback', page_no, total, PER_PAGE, status=status)}</div>"
        )
        return HTMLResponse(
            page(
                title="Muammo va takliflar",
                subtitle=f"Jami {number(total)} ta foydalanuvchi xabari",
                body=body,
                identity=identity,
                active="feedback",
            )
        )

    @router.post("/admin/feedback/{feedback_id}/status")
    async def feedback_status(feedback_id: int, request: Request) -> RedirectResponse:
        identity = _admin(request, settings, "feedback")
        form = await parse_form(request)
        verify_csrf(identity, form)
        next_status = form.get("status", "resolved")
        if next_status not in {"new", "resolved"}:
            raise HTTPException(400, "Holat noto‘g‘ri.")
        async with session_maker() as session:
            item = await session.get(FeedbackMessage, feedback_id)
            if item is None:
                raise HTTPException(404)
            item.status = next_status
            item.handled_by = identity.username if next_status == "resolved" else None
            item.handled_at = datetime.now(UTC) if next_status == "resolved" else None
            await _audit(
                session,
                request,
                identity,
                "feedback_status",
                "feedback",
                str(feedback_id),
                next_status,
            )
            await session.commit()
        return _go("/admin/feedback", "Xabar holati yangilandi.")

    @router.get("/admin/reports", response_class=HTMLResponse)
    async def reports_page(request: Request) -> HTMLResponse:
        identity = _admin(request, settings, "reports")
        body = _message(request) + "<section class='cards'><a class='card metric' href='/admin/export/users.csv'><small>CSV eksport</small><b style='font-size:18px'>Foydalanuvchilar</b></a><a class='card metric' href='/admin/export/payments.csv'><small>CSV eksport</small><b style='font-size:18px'>To‘lovlar</b></a><a class='card metric' href='/admin/export/scans.csv'><small>CSV eksport</small><b style='font-size:18px'>Tekshiruvlar</b></a><a class='card metric' href='/admin/export/audit.csv'><small>CSV eksport</small><b style='font-size:18px'>Audit jurnali</b></a></section>"
        return HTMLResponse(page(title="Hisobotlar", subtitle="Excel’da ochiladigan UTF-8 CSV fayllar", body=body, identity=identity, active="reports"))

    @router.get("/admin/export/{kind}.csv")
    async def export_csv(kind: str, request: Request) -> Response:
        _admin(request, settings, "reports")
        async with session_maker() as session:
            if kind == "users":
                data = (await session.execute(select(User, Wallet).outerjoin(Wallet, Wallet.user_id == User.id).order_by(User.id))).all(); rows = [["ID", "Telegram ID", "Username", "Ism", "Balans", "Ro‘yxatdan o‘tgan"]] + [[u.id, u.telegram_id, u.username or "", (u.first_name + " " + (u.last_name or "")).strip(), w.balance_words if w else 0, u.created_at.isoformat()] for u, w in data]
            elif kind == "payments":
                data = (await session.execute(select(PaymentOrder, User).join(User).order_by(PaymentOrder.id))).all(); rows = [["ID", "Telegram ID", "Paket", "So‘z", "Summa", "Holat", "Sana"]] + [[p.id, u.telegram_id, p.package_name, p.words, p.amount_uzs, p.status, p.created_at.isoformat()] for p, u in data]
            elif kind == "scans":
                data = (await session.execute(select(Submission, ExternalScan, User).join(User).outerjoin(ExternalScan, ExternalScan.submission_id == Submission.id).order_by(Submission.id))).all(); rows = [["ID", "Telegram ID", "Fayl", "So‘z", "Holat", "Originallik", "O‘xshashlik", "Sana"]] + [[s.id, u.telegram_id, s.filename, s.word_count, e.status if e else "", s.originality_score, s.plagiarism_score, s.created_at.isoformat()] for s, e, u in data]
            elif kind == "audit":
                data = (await session.scalars(select(AdminAudit).order_by(AdminAudit.id))).all(); rows = [["ID", "Admin", "Amal", "Obyekt", "Obyekt ID", "Tafsilot", "IP", "Sana"]] + [[a.id, a.admin_username, a.action, a.target_type, a.target_id, a.details, a.ip_address, a.created_at.isoformat()] for a in data]
            else: raise HTTPException(404, "Hisobot turi topilmadi.")
        return _csv_response(f"qvpmm_{kind}_{datetime.now(UTC):%Y%m%d}.csv", rows)

    @router.get("/admin/audit", response_class=HTMLResponse)
    async def audit_page(request: Request, page_no: int = Query(1, alias="page", ge=1)) -> HTMLResponse:
        identity = _admin(request, settings, "audit")
        async with session_maker() as session:
            total = await session.scalar(select(func.count(AdminAudit.id))) or 0
            rows = (await session.scalars(select(AdminAudit).order_by(AdminAudit.created_at.desc()).offset((page_no - 1) * PER_PAGE).limit(PER_PAGE))).all()
        table_rows = "".join(f"<tr><td>{a.created_at:%d.%m.%Y %H:%M}</td><td>{escape(a.admin_username)}</td><td><code>{escape(a.action)}</code></td><td>{escape(a.target_type)} {escape(a.target_id)}</td><td>{escape(a.details)}</td><td>{escape(a.ip_address)}</td></tr>" for a in rows) or '<tr><td colspan="6" class="empty">Audit yozuvlari yo‘q</td></tr>'
        body = f"<div class='card'><div class='table-wrap'><table><thead><tr><th>Vaqt</th><th>Admin</th><th>Amal</th><th>Obyekt</th><th>Tafsilot</th><th>IP</th></tr></thead><tbody>{table_rows}</tbody></table></div>{pagination('/admin/audit', page_no, total, PER_PAGE)}</div>"
        return HTMLResponse(page(title="Audit jurnali", subtitle="Admin paneldagi barcha muhim o‘zgarishlar", body=body, identity=identity, active="audit"))

    @router.get("/admin/admins", response_class=HTMLResponse)
    async def admins_page(request: Request) -> HTMLResponse:
        identity = _admin(request, settings)
        if not identity.can("*"): raise HTTPException(403)
        async with session_maker() as session: accounts = (await session.scalars(select(AdminAccount).order_by(AdminAccount.username))).all()
        admin_parts = []
        for account in accounts:
            account_state = (
                '<span class="badge ok">Faol</span>'
                if account.is_active
                else '<span class="badge bad">O‘chiq</span>'
            )
            toggle_label = "O‘chirish" if account.is_active else "Yoqish"
            admin_parts.append(
                f"<tr><td>{escape(account.username)}</td>"
                f"<td>{escape(ROLE_LABELS.get(account.role, account.role))}</td>"
                f"<td>{account_state}</td><td><form method='post' "
                f"action='/admin/admins/{account.id}/toggle'>{csrf_field(identity)}"
                f"<button class='small secondary'>{toggle_label}</button>"
                "</form></td></tr>"
            )
        rows = "".join(admin_parts) or (
            '<tr><td colspan="4" class="empty">Qo‘shimcha administrator yo‘q</td></tr>'
        )
        roles = "".join(f"<option value='{r}'>{escape(label)}</option>" for r, label in ROLE_LABELS.items() if r != "owner")
        body = _message(request) + f"<section class='grid2'><div class='card'><h2>Administrator qo‘shish</h2><form method='post' action='/admin/admins/create' class='form-grid'>{csrf_field(identity)}<label>Login<input name='username' required minlength='3'></label><label>Rol<select name='role'>{roles}</select></label><label class='wide'>Parol<input type='password' name='password' required minlength='10'></label><div><button>Qo‘shish</button></div></form></div><div class='card'><h2>Asosiy Owner</h2><p><b>{escape(settings.admin_web_username)}</b></p><p class='muted'>Bu administrator Railway Variables orqali himoyalangan va paneldan o‘chirib bo‘lmaydi.</p></div></section><br><section class='card'><h2>Qo‘shimcha administratorlar</h2><div class='table-wrap'><table><thead><tr><th>Login</th><th>Rol</th><th>Holat</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></section>"
        return HTMLResponse(page(title="Administratorlar", subtitle="Rollar va kirish huquqlarini boshqarish", body=body, identity=identity, active="admins"))

    @router.post("/admin/admins/create")
    async def admin_create(request: Request) -> RedirectResponse:
        identity = _admin(request, settings); form = await parse_form(request); verify_csrf(identity, form)
        if not identity.can("*"): raise HTTPException(403)
        username = form.get("username", "").strip(); password = form.get("password", ""); role = form.get("role", "operator")
        if len(username) < 3 or len(password) < 10 or role not in ROLE_LABELS or role == "owner": return _go("/admin/admins", "Ma’lumotlar talabga mos emas.", "bad")
        async with session_maker() as session:
            session.add(AdminAccount(username=username, password_hash=hash_password(password), role=role))
            await _audit(session, request, identity, "admin_create", "admin", username, role)
            try: await session.commit()
            except Exception: await session.rollback(); return _go("/admin/admins", "Bu login band.", "bad")
        return _go("/admin/admins", "Administrator qo‘shildi.")

    @router.post("/admin/admins/{account_id}/toggle")
    async def admin_toggle(account_id: int, request: Request) -> RedirectResponse:
        identity = _admin(request, settings); form = await parse_form(request); verify_csrf(identity, form)
        if not identity.can("*"): raise HTTPException(403)
        async with session_maker() as session:
            account = await session.get(AdminAccount, account_id)
            if account is None: raise HTTPException(404)
            account.is_active = not account.is_active
            await _audit(session, request, identity, "admin_toggle", "admin", account.username, f"active={account.is_active}"); await session.commit()
        return _go("/admin/admins", "Administrator holati yangilandi.")

    return router
