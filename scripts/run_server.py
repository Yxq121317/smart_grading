import argparse
import asyncio

import uvicorn

from app.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Smart Grading API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    config = uvicorn.Config(app, host=args.host, port=args.port)
    server = uvicorn.Server(config)

    async def serve() -> None:
        await server.serve()

    # Uvicorn 0.54 在 Windows 上默认用 ProactorEventLoop，psycopg async 不支持。
    asyncio.run(serve(), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
