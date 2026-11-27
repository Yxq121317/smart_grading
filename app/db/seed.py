from sqlalchemy import case, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ErrorCategory, Question

ERROR_CATEGORIES = [
    {"code": "info_filter", "name": "信息筛选错误", "description": "找错原文信息或遗漏关键句"},
    {"code": "concept_misread", "name": "概念理解偏差", "description": "对文中概念理解错误"},
    {"code": "incomplete_summary", "name": "概括不全", "description": "采分点缺失或概括不完整"},
    {
        "code": "argument_analysis",
        "name": "论证分析错误",
        "description": "论点、论据、论证方法判断错误",
    },
    {"code": "evidence_misuse", "name": "论据使用不当", "description": "引用或分析论据出错"},
    {"code": "expression", "name": "表达不规范", "description": "语言组织、条理、术语问题"},
    {"code": "off_topic", "name": "答非所问", "description": "回答与题干要求不符"},
    {"code": "blank", "name": "未作答", "description": "答案为空"},
    {"code": "mcq_wrong", "name": "选择题误选", "description": "选择题选了错误选项"},
]


async def seed_error_categories(session: AsyncSession) -> None:
    statement = (
        insert(ErrorCategory)
        .values(ERROR_CATEGORIES)
        .on_conflict_do_nothing(index_elements=[ErrorCategory.code])
    )
    await session.execute(statement)


async def apply_default_scores(
    session: AsyncSession,
    mcq: float = 3,
    subjective: float = 6,
) -> int:
    default_score = case(
        (Question.question_type == "single_choice", mcq),
        else_=subjective,
    )
    statement = (
        update(Question)
        .where(Question.max_score.is_(None))
        .values(max_score=default_score)
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(statement)
    await session.commit()
    return result.rowcount
