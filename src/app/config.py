import os

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field
from transformers import AutoTokenizer
from src.app.utils.logger import configure_logging, get_logger


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        cli_parse_args=False,
        cli_prog_name="Ulvek",
        cli_kebab_case=True,
        cli_implicit_flags=True,
        extra="ignore",
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    LOG_FILE: str | None = Field(
        default=None,
        description="Path to log file. If not set, logs only go to console.",
    )
    OPENROUTER_API_KEY: SecretStr = Field(
        default=..., min_length=1, description="Api Key for your model api provider"
    )
    MODEL_NAME: str = Field(
        default="openai/gpt-5-mini",
        description="AI model to use for generation",
    )
    BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenAI compatible API base url",
    )
    PROVIDER: str = Field(
        default="openrouter", description="Provider to use for model api"
    )
    EMBEDDING_MODEL: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B", description="Embedding model to use"
    )
    EMBEDDING_MODEL_DIMS: int = Field(
        default=1024, description="Embedding model dimensions"
    )
    SMALL_LLM_MODEL: str = Field(
        default="qwen/qwen3-235b-a22b-2507", description="For memory, and simple tasks"
    )
    MAX_CONTEXT_TOKENS: int = Field(
        default=128000, description="Maximum context tokens to use for the models"
    )


settings = AppConfig()

config = {
    "llm": {
        "provider": "openai",
        "config": {
            "api_key": settings.OPENROUTER_API_KEY.get_secret_value(),
            "model": settings.SMALL_LLM_MODEL,
            "openai_base_url": settings.BASE_URL,
        },
    },
    "vector_store": {
        "config": {
            "embedding_model_dims": settings.EMBEDDING_MODEL_DIMS,
        },
    },
    "embedder": {
        "provider": "huggingface",
        "config": {"model": settings.EMBEDDING_MODEL},
    },
}


configure_logging(settings)
logger = get_logger("ulvek")


tokenizer = AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL)
