from typing import Literal, Any
import uuid
import asyncio
import aiofiles
from langgraph.graph import START, END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from src.app.workflow.types import (
    WrapperState,
    checkpointer,
    FeedbackState,
    PlannerState,
)
from src.app.workflow.enums import MainRoutes, Interraction
from src.app.workflow.subgraphs.coding_workflow import worker_feedback_subgraph
from src.app.workflow.subgraphs.planning_workflow import heavy_subgraph
from src.app.workflow.utils import get_event_queue_from_config, build_static
import argparse
import logging
from src.app.agents.agent import (
    context_retriever_agent,
    conversational_agent,
    task_classification_agent,
    run_agent_with_events,
)
from src.app.agents.schemas import (
    AssembledContext,
    TaskType,
)
from langchain_core.messages import HumanMessage, AIMessage
from src.app.utils.converters import (
    token_count,
    convert_openai_to_pydantic_messages,
    convert_langgraph_to_openai_messages,
)
from src.app.utils.logger import get_logger, WorkflowLogger
from textwrap import dedent
from langchain_core.runnables.config import RunnableConfig

logger = get_logger(__name__)


# ------------------------------------------------------------------
# 3. Core nodes
# ------------------------------------------------------------------
# ---------------------------subgraphs nodes------------------------
async def worker_feedback_subgraph_start(state: WrapperState, config: RunnableConfig):
    logger.debug("Worker feedback subgraph start")
    worker_state = FeedbackState(
        messages_buffer=[state.messages_buffer[-1]],
        static_ctx=str(state.ctx),
    )
    logger.debug(f"Worker feedback subgraph start: {worker_state}")
    start_worker_graph = await worker_feedback_subgraph.ainvoke(
        worker_state, config=config
    )
    parse_worker_graph = FeedbackState(**start_worker_graph)
    proper_output = f"""
    Here is an overview of the changes I made:
    {parse_worker_graph.messages_buffer[-1].content}
    """
    return {"messages_buffer": state.messages_buffer + [AIMessage(proper_output)]}


async def heavy_subgraph_start(state: WrapperState, config: RunnableConfig):
    heavy_state = PlannerState(
        gathered_context=str(state.ctx),
        messages_buffer=[state.messages_buffer[-1]],
    )
    heavy_graph = await heavy_subgraph.ainvoke(heavy_state, config=config)
    parse_heavy_graph = PlannerState(**heavy_graph)

    return {
        "messages_buffer": state.messages_buffer
        + [AIMessage(parse_heavy_graph.gathered_context)]
    }


# ----------------------------nodes---------------------------------
async def router_node(
    state: WrapperState, config: RunnableConfig
) -> Literal[MainRoutes.CHAT, MainRoutes.CONTEXT, MainRoutes.PLAN, MainRoutes.CODE]:
    logger.debug(
        f"Task classification agent for message: {state.messages_buffer[-1].content}"
    )

    e = None

    prompt = dedent(f"""
    ##Available context so far
    {state.ctx}

    ##User input
    {state.messages_buffer[0].content}

    Based on the conversation and what we have gathered so far, what is the next step to take?
    """)

    if state.ctx_retry > 3:
        prompt += (
            "The context retry is at max available anymore dont routes to context agent"
        )

    event_queue = get_event_queue_from_config(config)

    async for item in run_agent_with_events(
        task_classification_agent,
        prompt,
    ):
        await event_queue.put(item)

        if isinstance(item, TaskType):
            e = item

    if e is None:
        raise RuntimeError("Task classification agent did not return a result")

    return e.task_type


async def context_node(state: WrapperState, config: RunnableConfig):
    prompt = f"""
    ## Context gathered so far
    {state.ctx}
    --- 
    ## User requested task
    {state.messages_buffer[0].content}
    Gather the necessary information to be able to implement the initial user request 
    """

    tokens = token_count(prompt)
    logger.debug(f"Context retriever agent of {tokens} agent for {prompt}")
    context_call = None
    event_queue = get_event_queue_from_config(config)

    async for run in run_agent_with_events(
        context_retriever_agent,
        prompt,
    ):
        await event_queue.put(run)
        if isinstance(run, AssembledContext):
            context_call = run

    if context_call is None:
        raise RuntimeError("Context agent did not return a result")

    else:
        new_ctx = state.ctx
        new_ctx.append(context_call.model_dump_json())

        return {
            "ctx": new_ctx,
        }


async def chat_node(state: WrapperState, config: RunnableConfig):
    openai_dicts = convert_openai_to_pydantic_messages(
        convert_langgraph_to_openai_messages(state.messages_buffer[:-1])
    )
    prompt = f"""
    ## Context to keep in mind
    {state.ctx}
    --- 
    {state.messages_buffer[-1].content}
    """
    logger.info(f"Chat: {prompt[:100]}...")
    tokens = token_count(prompt)
    logger.debug(f"chat retriever agent of {tokens} tokens for prompt: {prompt}")
    chat_call = None
    event_queue = get_event_queue_from_config(config)
    async for item in run_agent_with_events(
        conversational_agent,
        prompt,
        message_history=openai_dicts,
    ):
        await event_queue.put(item)
        if isinstance(item, str):
            chat_call = item

    if chat_call is None:
        raise RuntimeError("Chat agent did not return a result")

    return {
        "messages_buffer": state.messages_buffer + [AIMessage(chat_call)],
    }


# ------------------------------------------------------------------
# 4. Graphs construction
# ------------------------------------------------------------------
# -------------------------main wrapper graph state-----------------


wrapper_graph = (
    StateGraph(WrapperState)
    .add_node(MainRoutes.CHAT, chat_node)
    .add_node(
        MainRoutes.CONTEXT,
        context_node,
    )
    .add_node(MainRoutes.PLAN, heavy_subgraph_start)
    .add_node(MainRoutes.CODE, worker_feedback_subgraph_start)
    .add_conditional_edges(START, router_node)
    .add_conditional_edges(MainRoutes.CONTEXT, router_node)
    .add_edge(MainRoutes.CHAT, END)
    .add_edge(MainRoutes.PLAN, END)
    .add_edge(MainRoutes.CODE, END)
).compile(checkpointer=checkpointer)


# ------------------------------------------------------------------
# 5. Public API
# ------------------------------------------------------------------
async def inspect_and_log_events(event_queue: asyncio.Queue, output_file: str):
    """
    Consumes all events from the queue, logs them to the console,
    and writes them to a specified output file for analysis.
    """
    logger.info(
        f"Starting event inspection. Logging to console and writing to '{output_file}'."
    )
    try:
        async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
            while True:
                item = await event_queue.get()
                if item is None:
                    logger.info("Received end signal. Stopping inspector.")
                    break
                try:
                    await f.write(item + "\n---------------------------------\n")
                except TypeError:
                    await f.write(str(item) + "\n---------------------------------\n")

    except Exception as e:
        logger.error(f"Error in inspect_and_log_events: {e}", exc_info=True)
    finally:
        logger.info(
            f"Event inspection finished. File '{output_file}' has been written."
        )


async def run_main_graph(prompt: str, conversation_id: uuid.UUID, thread_id: str):
    event_queue: asyncio.Queue[str | dict | None] = asyncio.Queue()

    project_context = await build_static()
    initial_state = WrapperState(
        messages_buffer=[HumanMessage(content=prompt)],
        ctx=[f"### Project structure:\n{project_context}\n---"],
    )

    config: RunnableConfig = {
        "configurable": {"thread_id": conversation_id},
        "run_id": conversation_id,
        "metadata": {"thread_id": thread_id, "event_queue": event_queue},
    }

    tasks = [
        asyncio.create_task(
            graph_runner_with_interruption(
                wrapper_graph, initial_state, config, event_queue
            )
        ),
        asyncio.create_task(inspect_and_log_events(event_queue, "raw_events.log")),
    ]

    try:
        await asyncio.gather(*tasks)
        logger.info("Main graph execution completed successfully.")
    except asyncio.CancelledError:
        logger.warning("Tasks were cancelled.")
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()


async def graph_runner_with_interruption(
    graph: CompiledStateGraph,
    initial_state: WrapperState | Command,
    config: RunnableConfig,
    event_queue: asyncio.Queue[str | dict | None | Any],
):
    """Stream graph execution with recursive interrupt handling."""
    try:
        state = initial_state
        while True:
            async for item in graph.astream(
                state, config=config, stream_mode="updates", subgraphs=True
            ):
                if isinstance(item, tuple) and len(item) == 2:
                    path, payload = item
                    if "__interrupt__" in payload:
                        interrupt = payload["__interrupt__"][0]
                        value = interrupt.value
                        print("-" * 100)
                        print(f"Starting iteration {path}")
                        print("-" * 100)
                        print()

                        if value.get("type") == Interraction.FEEDBACK:
                            response = input("Feedback: ")
                        else:
                            response = input("Approve? (y/n): ").lower()

                        state = Command(resume=response)
                        break
                    else:
                        await event_queue.put(item)
                else:
                    await event_queue.put(item)
            else:
                break
    finally:
        await event_queue.put(None)


# --------------------------------------TEST RUNS-------------------------------------


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Set log level (default: info)",
    )
    args = parser.parse_args()

    # Map string to logging level
    level = getattr(logging, args.log_level.upper(), logging.INFO)
    WorkflowLogger.set_level(level)

    prompt = input("Please enter your prompt: " + "\n" + ">")
    WorkflowLogger.set_level(logging.DEBUG)

    await run_main_graph(
        prompt,
        uuid.uuid4(),
        "test",
    )


if __name__ == "__main__":
    asyncio.run(main())
