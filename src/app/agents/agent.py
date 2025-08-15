from pydantic_ai import Agent, Tool
from typing import TypeVar, Any, cast, AsyncGenerator
from pydantic_ai.messages import ModelMessage
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
import asyncio
from dataclasses import dataclass
from ..config import settings
from src.app.tools.interactive_tools import gather_docs_context
from src.app.tools.search_files import search_files
from src.app.utils.logger import get_logger
from src.app.agents.prompts.chat import CONVERSATIONAL_AGENT_PROMPT
from src.app.agents.prompts.reviewer import REVIEWER_AGENT_PROMPT
from src.app.agents.prompts.orchestrator import ORCHESTRATOR_AGENT_PROMPT
from src.app.agents.prompts.context_retriever import CONTEXT_RETRIEVER_PROMPT
from src.app.agents.prompts.worker import CODING_AGENT_FULL_PROMPT
from src.app.agents.prompts.task_classification import CLASSIFIER_AGENT_PROMPT
from src.app.agents.schemas import (
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
        execution_metadata["attempt_count"] = attempt + 1

        try:
            iter_kwargs: dict[str, Any] = {}
            if deps is not None:
                iter_kwargs["deps"] = deps

            async with agent.iter(
                prompt, message_history=message_history, **iter_kwargs
            ) as run:
                yield run

                async for node in run:
                    yield node

                    if run.result:
                        yield cast(AgentOutputT, run.result.output)
                        return

        except Exception as e:
            logger.error(
                f"Error in agent {agent.name} on attempt {attempt + 1}: {e}",
                exc_info=True,
            )

            if attempt == retries - 1:
                raise e

            delay = 2**attempt

            await asyncio.sleep(delay)

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
    system_prompt=(CODING_AGENT_FULL_PROMPT,),
    name="coding_agent",
    output_type=WorkerResult,
    tools=[
        Tool(search_files),
    ],
)

orchestrator_agent = Agent(
    model,
    system_prompt=(ORCHESTRATOR_AGENT_PROMPT,),
    output_type=ProjectPlan,
    name="orchestrator_agent",
)

context_retriever_agent = Agent(
    model,
    system_prompt=(CONTEXT_RETRIEVER_PROMPT,),
    name="context_gatherer_agent",
    output_type=AssembledContext,
    retries=5,
    tools=[
        Tool(search_files),
        Tool(gather_docs_context),
    ],
)

conversational_agent = Agent(
    model,
    system_prompt=(CONVERSATIONAL_AGENT_PROMPT),
    name="conversational_agent",
)
