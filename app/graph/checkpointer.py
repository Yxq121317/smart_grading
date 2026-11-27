from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings


@asynccontextmanager
async def create_checkpointer(settings: Settings):
    dsn = settings.mark_database_url.replace(
        "postgresql+psycopg://",
        "postgresql://",
    )
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        yield saver
