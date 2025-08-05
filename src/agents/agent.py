from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from ..config import settings
from pydantic import BaseModel, Field
from typing import Literal
from pydantic_ai import Tool
from src.tools.interactive_tools import gather_docs_context, prompt_user
from src.tools.search_files import search_files
from src.tools.files_edit import write_file, edit_file, batch_edit
from src.tools.terminal_executor import run_command, run_commands


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


class Task(BaseModel):
    task: str = Field(description="to-do item in markdown")


class TaskList(BaseModel):
    tasks: list[Task] = Field(description="Atomic, ordered to-do items in markdown")


class ReviewReport(BaseModel):
    issues: list[str] = Field(
        description="Short, actionable feedback bullets in markown todo task format"
    )


class EnhancedPrompt(BaseModel):
    user_query: str = Field(description="Focused request")


class TaskResult(BaseModel):
    output: str
    status: Literal["pending", "success", "needs_revision"]
    feedback: str = ""


class Evaluation(BaseModel):
    grade: Literal["pass", "revision_needed"] = Field(
        description="Does the solution satisfy requirements?"
    )
    feedback: str = Field(
        description="Specific improvement suggestions if revision needed"
    )


# -------------------------------------------------
# Agents (language-agnostic, Pydantic outputs)
# -------------------------------------------------

evaluator_agent = Agent(
    model,
    system_prompt=(
        "You are a rigorous code reviewer. Provide actionable feedback.",
        "Return JSON with: `grade` (pass/revision_needed) and `feedback`.",
    ),
    output_type=Evaluation,
    name="evaluator_agent",
)

coding_agent = Agent(
    model,
    system_prompt=(
        azure_safety_template,
        "You are an expert software engineer. "
        "Return ONLY the requested code snippet and a one-line explanation.",
        "Before any calling any edit or write_file , make sure you know the file and dependencies it is using ",
        "consider the whole app in your decisions",
        "use your search_files tool to verify the exact text to replace.",
    ),
    name="coding_agent",
    tools=[
        Tool(write_file),
        Tool(edit_file),
        Tool(search_files),
    ],
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

# must return the tools output to use as the context later
context_retriever_agent = Agent(
    model,
    system_prompt=(
        azure_safety_template,
        "you want to make sure you understand and have sufficient knowledge context."
        "keep gathering information using the tools until you estimate it is not necessary anymore. "
        "aggregate the output of the tools and return it raw",
    ),
    name="context gatherer agent",
    tools=[
        Tool(prompt_user),
        Tool(search_files),
        Tool(gather_docs_context),
    ],
)

conversational_agent = Agent(
    model,
    system_prompt=(
        azure_safety_template,
        "You are a helpful, engaging AI assistant. "
        "Conduct natural conversations, remember context throughout the discussion, "
        "ask clarifying questions when needed, and provide thoughtful responses. "
        "Be empathetic, concise, and focused on being genuinely helpful.",
    ),
    name="conversational_agent",
    tools=[
        Tool(prompt_user),
    ],
)
