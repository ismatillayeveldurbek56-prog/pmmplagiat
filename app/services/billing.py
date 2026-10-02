from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Wallet, WalletTransaction


async def get_or_create_wallet(session: AsyncSession, user_id: int) -> Wallet:
    wallet = await session.scalar(
        select(Wallet).where(Wallet.user_id == user_id).with_for_update()
    )
    if wallet is None:
        wallet = Wallet(user_id=user_id, balance_words=0)
        session.add(wallet)
        await session.flush()
    return wallet


async def wallet_balance(session: AsyncSession, user_id: int) -> int:
    wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
    return int(wallet.balance_words if wallet else 0)


async def credit_words(
    session: AsyncSession,
    *,
    user_id: int,
    words: int,
    reference: str,
    note: str = "",
) -> tuple[bool, int]:
    existing = await session.scalar(
        select(WalletTransaction).where(WalletTransaction.reference == reference)
    )
    if existing is not None:
        return False, existing.balance_after
    wallet = await get_or_create_wallet(session, user_id)
    wallet.balance_words += words
    transaction = WalletTransaction(
        user_id=user_id,
        kind="credit",
        amount_words=words,
        balance_after=wallet.balance_words,
        reference=reference,
        note=note,
    )
    session.add(transaction)
    return True, wallet.balance_words


async def debit_words(
    session: AsyncSession,
    *,
    user_id: int,
    words: int,
    reference: str,
    note: str = "",
) -> tuple[bool, int]:
    existing = await session.scalar(
        select(WalletTransaction).where(WalletTransaction.reference == reference)
    )
    if existing is not None:
        return True, existing.balance_after
    wallet = await get_or_create_wallet(session, user_id)
    if wallet.balance_words < words:
        return False, wallet.balance_words
    wallet.balance_words -= words
    session.add(
        WalletTransaction(
            user_id=user_id,
            kind="debit",
            amount_words=-words,
            balance_after=wallet.balance_words,
            reference=reference,
            note=note,
        )
    )
    return True, wallet.balance_words


async def refund_scan_words(
    session: AsyncSession,
    *,
    user_id: int,
    words: int,
    scan_id: str,
) -> tuple[bool, int]:
    debit = await session.scalar(
        select(WalletTransaction).where(WalletTransaction.reference == f"scan:{scan_id}")
    )
    if debit is None:
        return False, await wallet_balance(session, user_id)
    return await credit_words(
        session,
        user_id=user_id,
        words=words,
        reference=f"scan_refund:{scan_id}",
        note="Tekshiruv texnik xato bilan tugagani uchun qaytarildi",
    )
