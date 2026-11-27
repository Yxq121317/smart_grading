import asyncio
import sys

from app.core.config import Settings
from app.db.seed import apply_default_scores
from app.db.session import create_engine_and_factory

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main() -> None:
    settings = Settings()
    engine, factory = create_engine_and_factory(settings.mark_database_url)
    try:
        async with factory() as session:
            updated = await apply_default_scores(
                session,
                settings.default_mcq_score,
                settings.default_subjective_score,
            )
    finally:
        await engine.dispose()
    print(f"updated {updated} questions with default scores")


if __name__ == "__main__":
    asyncio.run(main())
