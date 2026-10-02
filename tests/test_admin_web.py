import httpx

from app.config import Settings
from app.database import create_engine_and_session, create_tables
from app.models import PaymentOrder, User
from app.web import create_web_app


async def test_admin_login_dashboard_and_management_pages() -> None:
    engine, session_maker = create_engine_and_session("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    async with session_maker() as session:
        user = User(telegram_id=998877, username="tester", first_name="Sinov")
        session.add(user)
        await session.flush()
        session.add(
            PaymentOrder(
                user_id=user.id,
                package_code="w10",
                package_name="10 000 so‘z",
                words=10_000,
                amount_uzs=10_000,
                status="pending",
                receipt_file_id="telegram-file-id",
                receipt_kind="photo",
            )
        )
        await session.commit()

    settings = Settings(
        BOT_TOKEN="123456:TEST",
        ADMIN_WEB_USERNAME="owner",
        ADMIN_WEB_PASSWORD="very-strong-password",
        ADMIN_WEB_SECRET="a-very-long-random-session-secret-value",
    )
    app = create_web_app(settings=settings, session_maker=session_maker)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        root = await client.get("/admin")
        assert root.status_code == 303
        assert root.headers["location"] == "/admin/login"

        login = await client.post(
            "/admin/login",
            data={"username": "owner", "password": "very-strong-password"},
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/admin/dashboard"
        assert "qvpmm_admin" in client.cookies

        dashboard = await client.get("/admin/dashboard")
        users = await client.get("/admin/users")
        payments = await client.get("/admin/payments")
        tariffs = await client.get("/admin/tariffs")
        scans = await client.get("/admin/scans")
        certificates = await client.get("/admin/certificates")
        reports = await client.get("/admin/reports")
        audit = await client.get("/admin/audit")

        assert dashboard.status_code == 200
        assert "Dashboard" in dashboard.text
        assert "Sinov" in users.text
        assert "10 000 so‘z" in payments.text
        assert "Tariflar" in tariffs.text
        assert scans.status_code == 200
        assert certificates.status_code == 200
        assert reports.status_code == 200
        assert "login" in audit.text
    await engine.dispose()


async def test_admin_rejects_wrong_password() -> None:
    engine, session_maker = create_engine_and_session("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    settings = Settings(
        BOT_TOKEN="123456:TEST",
        ADMIN_WEB_USERNAME="owner",
        ADMIN_WEB_PASSWORD="correct-password",
        ADMIN_WEB_SECRET="another-long-session-secret-value",
    )
    app = create_web_app(settings=settings, session_maker=session_maker)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/login",
            data={"username": "owner", "password": "wrong-password"},
        )
    assert response.status_code == 401
    assert "noto‘g‘ri" in response.text
    await engine.dispose()
