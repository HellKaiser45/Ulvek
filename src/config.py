from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from mem0 import Memory
from transformers import AutoTokenizer


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        cli_parse_args=True,
        cli_prog_name="Ulvek",
        cli_kebab_case=True,
        cli_implicit_flags=True,
        extra="ignore",
    )
    OPENROUTER_API_KEY: SecretStr = Field(
        default=..., min_length=1, description="Api Key for your model api provider"
    )
    MODEL_NAME: str = Field(
        default="moonshotai/kimi-k2", description="AI model to use for generation"
    )
    BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenAI compatible API base url",
    )
    PROVIDER: str = Field(
        default="openrouter", description="Provider to use for model api"
    )


def get_config() -> AppConfig:
    """Charge et valide la configuration"""
    try:
        return AppConfig()
    except Exception as e:
        print(f"Erreur de configuration : {e}")
        raise SystemExit(1)


def configure_cli():
    """Initialize CLI-ready settings with proper error handling"""
    try:
        settings = AppConfig()

        model = OpenAIModel(
            model_name=settings.MODEL_NAME,
            provider=OpenAIProvider(
                base_url=settings.BASE_URL,
                api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
            ),
        )
        return model

    except Exception as e:
        print(f"Configuration error: {e}")
        print("Please ensure you have:")
        print("1. A .env file with OPENROUTER_API_KEY")
        print("2. Or pass --openrouter-api-key via CLI")
        raise SystemExit(1)


generalConfig = get_config()

config = {
    "llm": {
        "provider": "openai",
        "config": {
            "api_key": generalConfig.OPENROUTER_API_KEY.get_secret_value(),
            "model": generalConfig.MODEL_NAME,
            "openai_base_url": generalConfig.BASE_URL,
        },
    },
    "vector_store": {
        "config": {
            "embedding_model_dims": 1024,
        },
    },
    "embedder": {
        "provider": "huggingface",
        "config": {"model": "Qwen/Qwen3-Embedding-0.6B"},
    },
}

m = Memory.from_config(config)
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-Embedding-0.6B")
