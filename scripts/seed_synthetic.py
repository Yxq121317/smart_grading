import argparse
import asyncio
import sys

from app.core.config import Settings
from app.db.session import create_engine_and_factory
from app.services.synthetic import seed_synthetic

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main(args: argparse.Namespace) -> None:
    settings = Settings()
    engine, factory = create_engine_and_factory(settings.mark_database_url)
    try:
        async with factory() as session:
            result = await seed_synthetic(
                session,
                args.exam_code,
                students=args.students,
                class_name=args.class_name,
                seed=args.seed,
            )
    finally:
        await engine.dispose()
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic class and submissions")
    parser.add_argument("--exam-code", default="2023-新高考Ⅰ卷")
    parser.add_argument("--students", type=int, default=10)
    parser.add_argument("--class-name", default="高二(1)班")
    parser.add_argument("--seed", type=int, default=42)
    asyncio.run(main(parser.parse_args()))
