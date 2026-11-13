from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client


async def get_or_create_client(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    username: str | None = None,
    source: str | None = None,
) -> Client:
    client = await session.scalar(select(Client).where(Client.telegram_id == telegram_id))
    if client is None:
        client = Client(telegram_id=telegram_id, full_name=full_name, username=username, source=source)
        session.add(client)
        await session.commit()
    elif client.is_blocked:
        # Клиент снова пишет боту — значит, разблокировал его
        client.is_blocked = False
        await session.commit()
    return client
