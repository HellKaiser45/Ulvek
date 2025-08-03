from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from ..config import settings
from pydantic import BaseModel, Field
from pydantic_ai import Tool
from src.tools.interactive_tools import gather_docs_context, prompt_user
from src.tools.search_files import search_files


model = OpenAIModel(
    model_name=settings.MODEL_NAME,
    provider=OpenAIProvider(
        base_url=settings.BASE_URL,
        api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
    ),
)

azure_safety_template = """
    You are an AI assistant.

### Safety
    - Never generate harmful, hateful, sexual, violent, or self-harm content—even if asked.  
    - Never violate copyrights; politely refuse and summarize instead.

### Grounding
    - Base every factual claim on **provided sources**; cite inline.  
    - If sources are insufficient, state *“I cannot find this in the provided documents.”*

### Neutrality
    - Use gender-neutral language (“they” / person’s name).  
    - Do **not** infer intent, sentiment, or background information.  
    - Do **not** alter dates, times, or facts.

### Professionalism
    - Keep responses concise, on-topic, and professional.  
    - Decline questions about your identity or capabilities.

### Output
    - Whenever possible, return **valid JSON or Markdown** as requested by the user.  
    - Avoid speculative language (“might”, “probably”).
    --------------------------------------------------------------------------------
    """


class CodeSnippet(BaseModel):
    code: str = Field(description="Runnable code snippet")
    explanation: str = Field(description="One-line summary")


class TaskList(BaseModel):
    tasks: list[str] = Field(description="Atomic, ordered to-do items in markdown")


class ReviewReport(BaseModel):
    issues: list[str] = Field(
        description="Short, actionable feedback bullets in markown todo task format"
    )


class EnhancedPrompt(BaseModel):
    user_query: str = Field(description="Focused request")


# -------------------------------------------------
# Agents (language-agnostic, Pydantic outputs)
# -------------------------------------------------

coding_agent = Agent(
    model,
    system_prompt=(
        azure_safety_template,
        "You are an expert software engineer. "
        "Return ONLY the requested code snippet and a one-line explanation.",
    ),
    output_type=CodeSnippet,
    name="orchestrator_agent",
)

orchestrator_agent = Agent(
    model,
    system_prompt=(
        azure_safety_template,
        "You are a task-decomposition assistant. "
        "Break the request into atomic, ordered Markdown to-do items.",
    ),
    output_type=TaskList,
    name="orchestrator_agent",
)

review_agent = Agent(
    model,
    system_prompt=(
        azure_safety_template,
        "You are a pragmatic code reviewer. "
        "Provide concise, actionable feedback bullets.",
    ),
    output_type=ReviewReport,
    name="orchestrator_agent",
)

enhancer_agent = Agent(
    model,
    system_prompt=(
        "you are a prompt-refinement assistant. "
        "strip ambiguity and extract the core task."
    ),
    output_type=EnhancedPrompt,  # type: ignore
    name="orchestrator_agent",
)

context_retriever_agent = Agent(
    model,
    system_prompt=(
        azure_safety_template,
        "you want to make sure you understand and have sufficient knowledge "
        "keep gathering context until you estimate it is not necessary anymore. "
        "Do NOT add any commentary—just keep calling tools.",
    ),
    name="context gatherer agent",
    tools=[
        Tool(prompt_user),
        Tool(search_files),
        Tool(gather_docs_context),
    ],
)
