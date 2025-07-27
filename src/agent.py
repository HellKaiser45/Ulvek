import os

from pydantic_ai import Agent, result
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

api_key = os.getenv("OPENROUTER_API_KEY")
print(f"API Key: {api_key}")  # Right after os.getenv()

model = OpenAIModel(
    "moonshotai/kimi-k2",
    provider=OpenAIProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        headers={
            "X-Title": "Agentic AI Code Assistant Backend"
        }
    ),
)

agent = Agent(
    name="Agentic AI Code Assistant Backend",
    model=model,
    output_type=str,
    system_prompt=(
        "you are an assistant that breaks down tasks into an ordered baby steps markdown todo list"
    ),
)


def main():
    response = agent.run_sync(
        "What are the steps to fully fledge agentic ai code assistant backend including multi-agents, memory, context management, and more?"
    )
    with open("agentic_ai_code_assistant_backend.md", "w") as f:
        f.write(response.output)


if __name__ == "__main__":
    main()
