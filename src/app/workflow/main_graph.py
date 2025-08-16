from typing import Literal
import uuid
import json
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
from src.app.workflow.enums import MainRoutes
from src.app.workflow.subgraphs.coding_workflow import worker_feedback_subgraph
from src.app.workflow.subgraphs.planning_workflow import heavy_subgraph
from src.app.workflow.utils import get_event_queue_from_config, build_static

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
from src.app.utils.logger import get_logger
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
        static_ctx=state.ctx,
    )
    logger.debug(f"Worker feedback subgraph start: {worker_state}")
    start_worker_graph = worker_feedback_subgraph.invoke(worker_state)
    parse_worker_graph = FeedbackState(**start_worker_graph)
    proper_output = f"""
    Here is an overview of the changes I made:
    {parse_worker_graph.messages_buffer[-1].content}
    """
    return {"messages_buffer": state.messages_buffer + [AIMessage(proper_output)]}


async def heavy_subgraph_start(state: WrapperState, config: RunnableConfig):
    heavy_state = PlannerState(
        gathered_context=state.ctx,
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
    logger.debug(f"Task classification agent for {state.messages_buffer[-1].content}")

    e = None
    prompt = dedent(f"""
    ## Available context
    {state.ctx}
    ### User input
    {state.messages_buffer[-1].content}
    
    """)
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
    openai_dicts = convert_openai_to_pydantic_messages(
        convert_langgraph_to_openai_messages(state.messages_buffer[:-1])
    )
    prompt = f"""
    ## Context gathered so far
    {state.ctx}
    --- 
    ## User requested task
    {state.messages_buffer[-1].content}
    Gather the necessary information to be able to plan the changes
    """
    tokens = token_count(prompt)
    logger.debug(f"Context retriever agent of {tokens} agent for {prompt}")
    context_call = None
    async for run in run_agent_with_events(
        context_retriever_agent,
        prompt,
        message_history=openai_dicts,
    ):
        if isinstance(run, AssembledContext):
            context_call = run

    if context_call is None:
        raise RuntimeError("Context agent did not return a result")
    code_snippets_structured = ""
    for code_snippet in context_call.code_snippets:
        if code_snippet.source == "documentation":
            documentation_provider = (
                code_snippet.documentation_provider or "not specified"
            )
            detail = f"""
            I found the following code snippet thanks to {code_snippet.source}:
            {code_snippet.code}
            I found it relevant to the task because:
            {code_snippet.relevance_reason}
            it is extracted from the {documentation_provider} documentation.
            """
            code_snippets_structured += "\n\n---\n\n" + detail
        elif code_snippet.source == "codebase":
            file_path = code_snippet.file_path or "not specified"
            start_line = code_snippet.start_line or "not specified"
            end_line = code_snippet.end_line or "not specified"
            detail = f"""
            I found the following code snippet thanks to {code_snippet.source}:
            {code_snippet.code}
            I found it relevant to the task because:
            {code_snippet.relevance_reason}
            it is extracted from the {file_path} file.
            It starts at line {start_line} and ends at line {end_line}.
            """
            code_snippets_structured += "\n\n---\n\n" + detail
        else:
            detail = f"""
            I found the following code snippet thanks to {code_snippet.source}:
            {code_snippet.code}
            I found it relevant to the task because:
            {code_snippet.relevance_reason}
            """
            code_snippets_structured += "\n\n---\n\n" + detail
    structured_output = f"""
    ## Summary of the gathered context:
        Here is a summary of the gathered context:
        {context_call.retrieval_summary}
    ## Project structure overview
        Here is an overview of the project structure:
        ### Key directories
        {"\n".join(context_call.project_structure.key_directories)}
        ### Key files
        {"\n".join(context_call.project_structure.key_files)}
        ### Technologies used
        {"\n".join(context_call.project_structure.technologies_used)}
        
        ### structure summary
        {context_call.project_structure.summary}
    ## Relevant code snippets (if any)
        Here are the relevant code snippets:
            {code_snippets_structured}
    ## External context (if any)
        Here is the external context:
            {
        "\n".join(
            f'''
                source: {ext.source}
                title: {ext.title}
                content: 
                {ext.content}
                this is relevant to the task because:
                {ext.relevance_reason}
                '''
            for ext in context_call.external_context
        )
    }
    ## Potential gaps in the context (if any)
        Here are the potential gaps in the context:
        {
        "\n".join(
            context_call.gaps_identified
            if context_call.gaps_identified
            else "no gaps identified"
        )
    }
    """
    return {
        "ctx": state.ctx + ("\n\n---\n\n" + structured_output),
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
        # Use aiofiles for non-blocking file operations in an async context
        async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
            while True:
                item = await event_queue.get()
                if item is None:  # Sentinel value to signal the end
                    logger.info("Received end signal. Stopping inspector.")
                    break

                # 1. Log the raw item to the console for real-time visibility
                logger.info(f"RAW_EVENT --- {item}")

                # 2. Write a structured, readable version to the log file
                try:
                    # Use json.dumps for pretty-printing dicts. Use default=str
                    # to handle potential non-serializable types like UUIDs.
                    json_str = json.dumps(item, indent=2, default=str)
                    await f.write(json_str + "\n---------------------------------\n")
                except TypeError:
                    # Fallback for items that are not JSON serializable at all
                    await f.write(str(item) + "\n---------------------------------\n")

    except Exception as e:
        logger.error(f"Error in inspect_and_log_events: {e}", exc_info=True)
    finally:
        logger.info(
            f"Event inspection finished. File '{output_file}' has been written."
        )


async def run_main_graph(
    prompt: str, conversation_id: uuid.UUID, thread_id: str
) -> None:
    """Execute the main workflow graph with unified event orchestration and interrupt handling."""
    event_queue: asyncio.Queue[str | dict | None] = asyncio.Queue()

    try:
        project_context = await build_static()
        initial_state = WrapperState(
            messages_buffer=[HumanMessage(content=prompt)],
            ctx=f"### Project structure:\n{project_context}\n---",
        )

        config: RunnableConfig = {
            "configurable": {"thread_id": conversation_id},
            "run_id": conversation_id,
            "metadata": {"thread_id": thread_id, "event_queue": event_queue},
        }

        await asyncio.gather(
            graph_runner_with_interruption(
                wrapper_graph, initial_state, config, event_queue
            ),
            inspect_and_log_events(event_queue, "raw_events.log"),
        )

        logger.info("Main graph execution completed successfully.")

    except Exception as e:
        logger.error(f"Graph execution failed: {e}", exc_info=True)
        raise


async def graph_runner_with_interruption(
    graph: CompiledStateGraph,
    initial_state: WrapperState | Command,
    config: RunnableConfig,
    event_queue: asyncio.Queue[str | dict | None],
):
    """Stream graph execution with recursive interrupt handling."""
    try:
        async for item in graph.astream(
            initial_state, config=config, stream_mode="updates", subgraphs=True
        ):
            if isinstance(item, dict) and "__interrupt__" in item:
                payload = item["__interrupt__"][0].value

                if payload["type"] == "FEEDBACK":
                    response = input("Feedback: ")
                else:
                    response = input("Approve? (y/n): ").lower() == "y"

                await graph_runner_with_interruption(
                    graph, Command(resume=response), config, event_queue
                )
                return

            await event_queue.put(item)
    finally:
        await event_queue.put(None)


# --------------------------------------TEST RUNS-------------------------------------


async def main():
    prompt = input("Please enter your prompt: " + "\n" + ">")

    await run_main_graph(
        prompt,
        uuid.uuid4(),
        "test",
    )


if __name__ == "__main__":
    asyncio.run(main())
