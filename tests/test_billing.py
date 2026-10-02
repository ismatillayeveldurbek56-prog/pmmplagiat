from sqlalchemy import select

from app.database import create_engine_and_session, create_tables
from app.models import User, WalletTransaction
from app.services.billing import credit_words, debit_words, refund_scan_words, wallet_balance


async def test_wallet_credit_debit_refund_and_idempotency() -> None:
    engine, session_maker = create_engine_and_session("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    async with session_maker() as session:
        user = User(telegram_id=123, first_name="Test")
        session.add(user)
        await session.flush()

        created, balance = await credit_words(
            session,
            user_id=user.id,
            words=10_000,
            reference="payment:1",
        )
        assert created is True
        assert balance == 10_000

        created_again, balance = await credit_words(
            session,
            user_id=user.id,
            words=10_000,
            reference="payment:1",
        )
        assert created_again is False
        assert balance == 10_000

        debited, balance = await debit_words(
            session,
            user_id=user.id,
            words=1_200,
            reference="scan:abc",
        )
        assert debited is True
        assert balance == 8_800

        refunded, balance = await refund_scan_words(
            session,
            user_id=user.id,
            words=1_200,
            scan_id="abc",
        )
        assert refunded is True
        assert balance == 10_000

        refunded_again, balance = await refund_scan_words(
            session,
            user_id=user.id,
            words=1_200,
            scan_id="abc",
        )
        assert refunded_again is False
        assert balance == 10_000
        assert await wallet_balance(session, user.id) == 10_000

        transactions = (await session.scalars(select(WalletTransaction))).all()
        assert len(transactions) == 3
    await engine.dispose()


async def test_wallet_blocks_insufficient_balance() -> None:
    engine, session_maker = create_engine_and_session("sqlite+aiosqlite:///:memory:")
    await create_tables(engine)
    async with session_maker() as session:
        user = User(telegram_id=456, first_name="Test")
        session.add(user)
        await session.flush()
        debited, balance = await debit_words(
            session,
            user_id=user.id,
            words=100,
            reference="scan:no-money",
        )
        assert debited is False
        assert balance == 0
    await engine.dispose()
