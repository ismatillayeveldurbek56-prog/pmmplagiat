from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base, Tariff


def create_engine_and_session(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"timeout": 30}

    engine = create_async_engine(database_url, **engine_kwargs)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_maker


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        tariff_count = await session.scalar(select(func.count(Tariff.id))) or 0
        if tariff_count == 0:
            session.add_all(
                [
                    Tariff(
                        code="w10", name="10 000 so‘z", words=10_000,
                        amount_uzs=10_000, sort_order=10,
                    ),
                    Tariff(
                        code="w25", name="25 000 so‘z", words=25_000,
                        amount_uzs=22_000, sort_order=20,
                    ),
                    Tariff(
                        code="w50", name="50 000 so‘z", words=50_000,
                        amount_uzs=40_000, sort_order=30,
                    ),
                    Tariff(
                        code="w100", name="100 000 so‘z", words=100_000,
                        amount_uzs=75_000, sort_order=40,
                    ),
                ]
            )
            await session.commit()


async def session_scope(
    session_maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_maker() as session:
        yield session
