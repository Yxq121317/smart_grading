import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routers.calibration import router as calibration_router
from app.api.routers.demo import router as demo_router
from app.api.routers.dev import router as dev_router
from app.api.routers.exams import router as exams_router
from app.api.routers.grading import router as grading_router
from app.api.routers.reports import router as reports_router
from app.api.routers.review import router as review_router
from app.api.routers.rubrics import router as rubrics_router
from app.api.routers.submissions import router as submissions_router
from app.core.config import Settings
from app.core.config import settings as default_settings
from app.db.session import create_engine_and_factory
from app.graph.builder import build_grading_graph
from app.graph.checkpointer import create_checkpointer
from app.services.grading import GradingService, mark_stale_runs
from app.services.llm import LLMClient, build_openai_client

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    llm=None,
    checkpointer=None,
) -> FastAPI:
    resolved = settings or default_settings
    engine = None
    if session_factory is None:
        engine, session_factory = create_engine_and_factory(resolved.mark_database_url)

    resolved_llm = llm or LLMClient(
        build_openai_client(resolved),
        resolved.model_name,
        timeout=resolved.llm_timeout_seconds,
        max_retries=resolved.llm_max_retries,
        concurrency=resolved.grading_concurrency,
        settings=resolved,
    )

    graph = None
    grading_service = None
    if checkpointer is not None:
        graph = build_grading_graph(
            resolved_llm,
            session_factory,
            resolved,
            checkpointer,
        )
        grading_service = GradingService(graph, session_factory, resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if checkpointer is None:
            async with create_checkpointer(resolved) as saver:
                nonlocal_graph = build_grading_graph(
                    resolved_llm,
                    session_factory,
                    resolved,
                    saver,
                )
                app.state.graph = nonlocal_graph
                app.state.grading_service = GradingService(
                    nonlocal_graph,
                    session_factory,
                    resolved,
                )
                await mark_stale_runs(session_factory)
                yield
        else:
            await mark_stale_runs(session_factory)
            yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="Smart Grading", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.session_factory = session_factory
    app.state.llm = resolved_llm
    app.state.graph = graph
    app.state.grading_service = grading_service
    app.include_router(exams_router)
    app.include_router(submissions_router)
    app.include_router(grading_router)
    app.include_router(review_router)
    app.include_router(calibration_router)
    app.include_router(rubrics_router)
    app.include_router(reports_router)
    app.include_router(demo_router)
    app.include_router(dev_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount(
        "/",
        StaticFiles(directory=Path(__file__).parent / "static", html=True),
        name="static",
    )
    return app


app = create_app()
