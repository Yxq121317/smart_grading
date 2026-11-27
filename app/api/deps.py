from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.grading import GradingService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_grading_service(request: Request) -> GradingService:
    return request.app.state.grading_service


def get_llm(request: Request):
    return request.app.state.llm
