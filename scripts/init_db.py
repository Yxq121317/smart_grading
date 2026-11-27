import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db.seed import seed_error_categories
from app.db.session import create_engine_and_factory

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]


async def seed_categories(settings: Settings, database: str) -> None:
    url = make_url(settings.mark_database_url).set(database=database)
    engine, factory = create_engine_and_factory(
        url.render_as_string(hide_password=False)
    )
    try:
        async with factory() as session:
            await seed_error_categories(session)
            await session.commit()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply db/schema.sql and seed error categories")
    parser.add_argument("--container", default="agent_test-postgres")
    parser.add_argument("--database", default="Mark")
    parser.add_argument("--user", default="postgres")
    args = parser.parse_args()

    schema = (ROOT / "db" / "schema.sql").read_bytes()
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            args.container,
            "psql",
            "-U",
            args.user,
            "-d",
            args.database,
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
        ],
        input=schema,
        check=True,
    )
    asyncio.run(seed_categories(Settings(), args.database))
    print(f"schema applied to {args.database}; error categories seeded")


if __name__ == "__main__":
    main()
