from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from typing import Optional
from ..config import AppConfig, get_config


class CodingAgent:
    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config if config is not None else get_config()
        self.agent = self._create_agent()

    def _create_agent(self) -> Agent:
        return Agent(
            name="Ulvek Coding Agent",
            system_prompt="Expert en génération de code Python",
            model=OpenAIModel(
                model_name=self.config.MODEL_NAME,
                provider=OpenAIProvider(
                    base_url=self.config.BASE_URL,
                    api_key=self.config.OPENROUTER_API_KEY.get_secret_value(),
                ),
            ),
        )

    def generate(self, prompt: str) -> str:
        """Exécute une tâche de génération"""
        return self.agent.run_sync(prompt).output
