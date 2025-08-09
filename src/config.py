from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field
from transformers import AutoTokenizer


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

    @classmethod
    def get_rich_click_config(cls):
        from rich_click import RichHelpConfiguration

        return RichHelpConfiguration(
            text_markup="markdown",
            style_option="bold blue",
            style_argument="bold cyan",
            style_command="bold magenta",
            style_switch="bold green",
            style_metavar="bold yellow",
            style_usage="bold",
            style_header_text="bold",
            style_footer_text="italic dim",
            style_option_help="default",
            style_option_default="dim",
            style_errors_suggestion="italic yellow",
            style_errors_panel_border="red",
            style_aborted="red bold",
            errors_suggestion="Try running the '--help' flag for more information.",
            show_arguments=True,
            group_arguments_options=False,
            width=100,
            max_width=120,
            style_options_table_leading=0,
            style_options_table_box="SIMPLE",
            style_commands_table_leading=0,
            style_commands_table_box="SIMPLE",
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


tokenizer = AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL)
