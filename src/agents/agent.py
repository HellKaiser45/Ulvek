from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from ..config import settings
from pydantic_ai import Tool
from src.tools.interactive_tools import gather_docs_context, prompt_user
from src.tools.search_files import search_files
from src.tools.files_edit import write_file, edit_file
from src.agents.prompts.chat import CONVERSATIONAL_AGENT_PROMPT
from src.agents.prompts.reviewer import REVIEWER_AGENT_PROMPT
from src.agents.prompts.orchestrator import ORCHESTRATOR_AGENT_PROMPT
from src.agents.prompts.context_retriever import CONTEXT_RETRIEVER_PROMPT
from src.agents.prompts.worker import CODING_AGENT_FULL_PROMPT
from src.agents.prompts.task_classification import CLASSIFIER_AGENT_PROMPT
from src.agents.schemas import (
    Evaluation,
    WorkerResult,
    ProjectPlan,
    AssembledContext,
    TaskType,
)

model = OpenAIModel(
    model_name=settings.MODEL_NAME,
    provider=OpenAIProvider(
        base_url=settings.BASE_URL,
        api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
    ),
)

# -------------------------------------------------
# Agents definitions
# -------------------------------------------------

task_classification_agent = Agent(
    model,
    system_prompt=CLASSIFIER_AGENT_PROMPT,
    name="task_classification_agent",
    output_type=TaskType,
)

evaluator_agent = Agent(
    model,
    system_prompt=(REVIEWER_AGENT_PROMPT),
    output_type=Evaluation,
    name="evaluator_agent",
)

coding_agent = Agent(
    model,
    system_prompt=(CODING_AGENT_FULL_PROMPT,),
    name="coding_agent",
    output_type=WorkerResult,
    tools=[
        Tool(write_file),
        Tool(edit_file),
        Tool(search_files),
    ],
)

orchestrator_agent = Agent(
    model,
    system_prompt=(ORCHESTRATOR_AGENT_PROMPT,),
    output_type=ProjectPlan,
    name="orchestrator_agent",
)

# must return the tools output to use as the context later
context_retriever_agent = Agent(
    model,
    system_prompt=(CONTEXT_RETRIEVER_PROMPT,),
    name="context gatherer agent",
    output_type=AssembledContext,
    tools=[
        Tool(prompt_user),
        Tool(search_files),
        Tool(gather_docs_context),
    ],
)

conversational_agent = Agent(
    model,
    system_prompt=(CONVERSATIONAL_AGENT_PROMPT,),
    name="conversational_agent",
)
