from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mark_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/Mark"
    test_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/Mark_test"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model_name: str = "deepseek-chat"
    llm_timeout_seconds: float = 60
    llm_max_retries: int = 2
    grading_concurrency: int = 5
    review_confidence_threshold: float = 0.75
    default_mcq_score: float = 3
    default_subjective_score: float = 6
    langfuse_enabled: bool = True
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    prompt_version: str = "v1"


settings = Settings()
