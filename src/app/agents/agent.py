from pydantic_ai import Agent, Tool
import collections.abc
from typing import TypeVar, Any, cast, AsyncGenerator
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models.mistral import MistralModel
import asyncio
from dataclasses import dataclass
from ..config import settings
from src.app.tools.interactive_tools import (
    gather_docs_context,
    gather_docs_context_description,
)
from src.app.tools.search_files import (
    search_files,
    similarity_search,
)
from src.app.utils.logger import get_logger
from src.app.agents.prompts.chat import CONVERSATIONAL_AGENT_PROMPT
from src.app.agents.prompts.reviewer import REVIEWER_AGENT_PROMPT
from src.app.agents.prompts.orchestrator import ORCHESTRATOR_AGENT_PROMPT
from src.app.agents.prompts.context_retriever import CONTEXT_RETRIEVER_PROMPT
from src.app.agents.prompts.worker import CODING_AGENT_FULL_PROMPT
from src.app.agents.prompts.task_classification import CLASSIFIER_AGENT_PROMPT
from src.app.agents.prompts.unit_test_generator import UNIT_TEST_GENERATOR_PROMPT
from src.app.agents.schemas import (
    Evaluation,
    ProjectPlan,
    GatheredContext,
    TaskType,
    FilePlan,
)
from src.app.tools.file_operations import (
    get_line_content,
    get_range_content,
    read_file_content,
    find_text_in_file,
)
from tenacity import (
    AsyncRetrying,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
    retry_if_exception_message,
)

logger = get_logger(__name__)

model = OpenAIModel(
    settings.MODEL_NAME,
    provider=OpenRouterProvider(
        api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
    ),
)

# -------------------Event Types for Better Logging-----------------------


@dataclass
class AgentExecutionEvent:
    """Structured event from agent execution for better observability"""

    agent_name: str
    event_type: str
    content: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class AgentResult:
    """Wrapper for agent results with execution metadata"""

    output: Any
    agent_name: str
    execution_metadata: dict[str, Any]


# -------------------Helpers-----------------------

AgentDepsT = TypeVar("AgentDepsT")
AgentOutputT = TypeVar("AgentOutputT")

# ------------------------------------------------------------------
# Enhanced event handler with detailed logging
# ------------------------------------------------------------------


async def run_agent_with_events(
    agent: Agent[AgentDepsT, AgentOutputT],
    prompt: str,
    message_history: list[ModelMessage] | None = None,
    retries: int = 3,
    deps: AgentDepsT | None = None,
) -> AsyncGenerator[AgentExecutionEvent | AgentResult | AgentOutputT | Any]:
    """
    Run agent and yield detailed execution events for comprehensive observability.

    This function provides granular insight into agent execution by yielding structured
    events for every significant operation: model requests, tool calls, streaming text,
    errors, and final results.

    Args:
        agent: The PydanticAI agent to execute
        prompt: User input prompt for the agent
        message_history: Optional conversation history
        retries: Number of retry attempts on failure
        deps: Optional dependencies for agent execution

    Yields:
        AgentExecutionEvent: Structured events during execution
        AgentResult: Final result with execution metadata

    Raises:
        RuntimeError: If all retry attempts fail
    """
    execution_metadata = {
        "attempt_count": 0,
        "total_tokens": 0,
        "model_requests": 0,
        "tool_calls": 0,
        "streaming_events": 0,
    }

    for attempt in range(retries):
        attempt = (attempt + 1) if attempt else 1
        run = None

        try:
            iter_kwargs: dict[str, Any] = {}
            if deps is not None:
                iter_kwargs["deps"] = deps

            async with agent.iter(
                prompt, message_history=message_history, **iter_kwargs
            ) as run:
                yield run
                logger.debug(
                    f"Agent {agent.name} has currently a context lenght of: {run.usage().total_tokens}"
                )
                if isinstance(run, collections.abc.AsyncIterable):
                    async for node in run:
                        yield node

                    if run.result:
                        yield cast(AgentOutputT, run.result.output)
                        return

                message_history = ModelMessagesTypeAdapter.validate_python(
                    run.all_messages()
                )

        except UnexpectedModelBehavior as e:
            if "finish_reason" in str(e) or "Received empty model response" in str(e):
                logger.warning(
                    f"Agent {agent.name} failed on attempt {attempt} with error: {e}",
                )
                logger.warning(f"Here was the last run object: {run}")
                if attempt == retries:
                    raise e

                delay = 10**attempt

                await asyncio.sleep(delay)

                continue
            elif "Received empty model response" in str(e):
                logger.warning(
                    f"Agent {agent.name} failed on attempt {attempt} with error: {e}, retrying...",
                )
                if attempt == retries:
                    raise e

                delay = 10**attempt

                await asyncio.sleep(delay)
                continue

            else:
                logger.error(
                    f"Agent {agent.name} failed on attempt {attempt + 1} with error: {e}",
                )
                logger.error(f"Here was the last run object: {run}")
                raise e

        except Exception as e:
            logger.error(
                f"Agent {agent.name} failed on attempt {attempt + 1} with error: {e}",
            )
            logger.error(f"Here was the last run object: {run}")
            raise e

    raise RuntimeError(f"Agent {agent.name} failed after {retries} retries.")


# -------------------------------------------------
# Agents definitions (unchanged)
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
    system_prompt=(CODING_AGENT_FULL_PROMPT),
    name="coding_agent",
    output_type=FilePlan,
    retries=5,
    tools=[
        Tool(read_file_content),
        Tool(get_line_content),
        Tool(get_range_content),
        Tool(find_text_in_file),
    ],
)

orchestrator_agent = Agent(
    model,
    system_prompt=(ORCHESTRATOR_AGENT_PROMPT),
    output_type=ProjectPlan,
    name="orchestrator_agent",
)

context_retriever_agent = Agent(
    model,
    system_prompt=(CONTEXT_RETRIEVER_PROMPT),
    name="context_gatherer_agent",
    output_type=GatheredContext,
    tools=[
        Tool(search_files),
        Tool(similarity_search),
        Tool(gather_docs_context, description=gather_docs_context_description),
    ],
)

conversational_agent = Agent(
    model,
    system_prompt=(CONVERSATIONAL_AGENT_PROMPT),
    name="conversational_agent",
)
