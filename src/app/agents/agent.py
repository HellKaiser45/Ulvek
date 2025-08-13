from pydantic_ai import (
    Agent,
    capture_run_messages,
    UnexpectedModelBehavior,
    Tool,
)
from pydantic_ai.messages import (
    AgentStreamEvent,
    HandleResponseEvent,
    PartStartEvent,
    PartDeltaEvent,
    TextPartDelta,
    ToolCallPartDelta,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    FinalResultEvent,
)
from typing import TypeVar, Any, cast
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
import asyncio
import json
from collections.abc import AsyncIterable
from ..config import settings
from src.app.tools.interactive_tools import gather_docs_context, prompt_user
from src.app.tools.search_files import search_files
from src.app.tools.files_edit import write_file, edit_file
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
    AgentDeps,
)
from src.app.utils.frontends_adapters.interaction_manager import (
    encode_event,
    send_event,
    emit_text_message_start,
    emit_text_message_content,
    emit_text_message_end,
    emit_tool_call_start,
    emit_tool_call_args,
    emit_tool_call_end,
    emit_tool_call_result,
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


# ------------------------------------------------------------------
# 1. 100 % complete AG-UI event handler
# ------------------------------------------------------------------
async def _agui_event_handler(
    run_id: str,
    events: AsyncIterable[AgentStreamEvent | HandleResponseEvent],
) -> None:
    open_text_msg_id: str | None = None
    open_tool_call_id: str | None = None

    async for ev in events:
        # 1) TEXT STREAMING -----------------------------------------------------
        if isinstance(ev, PartStartEvent):
            start_ev, msg_id = emit_text_message_start()
            await send_event(run_id, encode_event(start_ev))
            open_text_msg_id = msg_id

        elif isinstance(ev, PartDeltaEvent):
            if isinstance(ev.delta, TextPartDelta):
                assert open_text_msg_id is not None
                delta_ev = emit_text_message_content(
                    open_text_msg_id, ev.delta.content_delta
                )
                await send_event(run_id, encode_event(delta_ev))

            elif isinstance(ev.delta, ToolCallPartDelta):
                # First fragment -> start tool call
                if open_tool_call_id is None:
                    start_ev, tool_id = emit_tool_call_start(
                        ev.delta.tool_name_delta
                        if ev.delta.tool_name_delta
                        else "unknown tool"
                    )
                    await send_event(run_id, encode_event(start_ev))
                    open_tool_call_id = tool_id

                # JSON-encode the args delta fragment
                args_json = json.dumps(ev.delta.args_delta, ensure_ascii=False)
                args_ev = emit_tool_call_args(open_tool_call_id, args_json)
                await send_event(run_id, encode_event(args_ev))

        # 2) TOOL EXECUTION EVENTS ---------------------------------------------
        elif isinstance(ev, FunctionToolCallEvent):
            # Full tool call (args known)
            if open_tool_call_id is None:
                start_ev, tool_id = emit_tool_call_start(
                    str(ev.part.tool_name)  # cast to str
                )
                await send_event(run_id, encode_event(start_ev))
                open_tool_call_id = tool_id

            args_json = json.dumps(ev.part.args, ensure_ascii=False)
            args_ev = emit_tool_call_args(open_tool_call_id, args_json)
            await send_event(run_id, encode_event(args_json))

        elif isinstance(ev, FunctionToolResultEvent):
            assert open_tool_call_id is not None
            end_ev = emit_tool_call_end(open_tool_call_id)
            await send_event(run_id, encode_event(end_ev))

            # Tool result as a separate message
            _, msg_id = emit_text_message_start()
            result_ev = emit_tool_call_result(
                msg_id, open_tool_call_id, str(ev.result.content)
            )
            await send_event(run_id, encode_event(result_ev))
            open_tool_call_id = None

        elif isinstance(ev, FinalResultEvent):
            if open_text_msg_id is not None:
                end_ev = emit_text_message_end(open_text_msg_id)
                await send_event(run_id, encode_event(end_ev))
                open_text_msg_id = None

    # Clean-up -----------------------------------------------------------
    if open_text_msg_id is not None:
        end_ev = emit_text_message_end(open_text_msg_id)
        await send_event(run_id, encode_event(end_ev))
    if open_tool_call_id is not None:
        end_ev = emit_tool_call_end(open_tool_call_id)
        await send_event(run_id, encode_event(end_ev))


async def run_agent_safe(
    agent: Agent[AgentDepsT, AgentOutputT],
    prompt: str | list[str],
    message_history: list[dict[str, str]] | None = None,
    retries: int = 3,
    deps: AgentDepsT | None = None,
    **kwargs,
) -> AgentOutputT:
    run_id = getattr(deps, "run_id", "unknown") if deps else "unknown"

    def make_handler(rid: str):
        async def handler(
            events: AsyncIterable[AgentStreamEvent | HandleResponseEvent],
        ) -> None:
            await _agui_event_handler(rid, events)

        return handler

    for attempt in range(retries):
        with capture_run_messages() as messages:
            try:
                run_kwargs: dict[str, Any] = {
                    "event_stream_handler": make_handler(rid=run_id),
                }
                if deps is not None:
                    run_kwargs["deps"] = deps
                if message_history is not None:
                    run_kwargs["message_history"] = message_history
                run_kwargs.update(kwargs)

                result = await agent.run(prompt, **kwargs)

                return cast(AgentOutputT, result.output)
            except UnexpectedModelBehavior as error:
                logger.error(f"Unexpected model behavior error: {error}")
                logger.debug(f"cause of the error: {error.__cause__}")
                logger.debug(f"meessages: {messages}")
                delay = 2**attempt
                logger.debug(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"Error in agent: {e}")
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
    deps_type=AgentDeps,
)


evaluator_agent = Agent(
    model,
    system_prompt=(REVIEWER_AGENT_PROMPT),
    output_type=Evaluation,
    name="evaluator_agent",
    deps_type=AgentDeps,
)

coding_agent = Agent(
    model,
    system_prompt=(CODING_AGENT_FULL_PROMPT,),
    name="coding_agent",
    output_type=WorkerResult,
    deps_type=AgentDeps,
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
    deps_type=AgentDeps,
    name="orchestrator_agent",
)

# must return the tools output to use as the context later
context_retriever_agent = Agent(
    model,
    system_prompt=(CONTEXT_RETRIEVER_PROMPT,),
    name="context gatherer agent",
    output_type=AssembledContext,
    retries=5,
    deps_type=AgentDeps,
    tools=[
        Tool(prompt_user),
        Tool(search_files),
        Tool(gather_docs_context),
    ],
)

conversational_agent = Agent(
    model,
    system_prompt=(CONVERSATIONAL_AGENT_PROMPT),
    deps_type=AgentDeps,
    name="conversational_agent",
)
