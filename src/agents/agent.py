from pydantic_ai import Agent, capture_run_messages, UnexpectedModelBehavior, Tool
from pydantic_ai.agent import AgentRunResult
from typing import TypeVar
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
import asyncio
from ..config import settings
from src.tools.interactive_tools import gather_docs_context, prompt_user
from src.tools.search_files import search_files
from src.tools.files_edit import write_file, edit_file
from src.utils.logger import get_logger
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

logger = get_logger(__name__)

model = OpenAIModel(
    model_name=settings.MODEL_NAME,
    provider=OpenAIProvider(
        base_url=settings.BASE_URL,
        api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
    ),
)
# -------------------Helpers-----------------------

AgentDepsT = TypeVar("AgentDepsT")  # Usually None or a dependency type
AgentOutputT = TypeVar(
    "AgentOutputT"
)  # The actual output data type (str, MyModel, etc.)


async def run_agent_safe(
    agent: Agent[AgentDepsT, AgentOutputT],
    prompt: str | list[str],
    message_history: list[dict[str, str]] | None = None,
    retries: int = 3,
    deps: AgentDepsT | None = None,
    **kwargs,
) -> AgentRunResult[AgentOutputT]:
    for attempt in range(retries):
        with capture_run_messages() as messages:
            try:
                if deps:
                    kwargs["deps"] = deps
                if message_history:
                    kwargs["message_history"] = message_history
                result = await agent.run(prompt, **kwargs)
                return result
            except UnexpectedModelBehavior as error:
                logger.error(f"Unexpected model behavior error: {error}")
                logger.debug(f"cause of the error: {error.__cause__}")
                logger.debug(f"meessages: {messages}")
                delay = 2**attempt
                logger.debug(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"Error: {e}")
                raise e

    raise RuntimeError("Too many finish_reason='error' responses")


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
    retries=5,
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
