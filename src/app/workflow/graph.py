from __future__ import annotations
from pydantic import BaseModel
from typing import Literal, cast
import uuid
import json
import asyncio
import aiofiles
from langgraph.graph import START, END, StateGraph
from pydantic_ai.messages import (
    AgentStreamEvent,
    HandleResponseEvent,
    PartDeltaEvent,
    TextPartDelta,
)
from src.app.agents.agent import (
    orchestrator_agent,
    coding_agent,
    evaluator_agent,
    context_retriever_agent,
    conversational_agent,
    task_classification_agent,
    run_agent_with_events,
)
from src.app.agents.schemas import (
    ExecutionStep,
    Route,
    AgentDeps,
    Evaluation,
    ProjectPlan,
    AssembledContext,
    WorkerResult,
    TaskType,
    Interraction,
)
from src.app.tools.codebase import process_file, get_non_ignored_files
from langchain_core.messages import HumanMessage, AIMessage, AnyMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from src.app.utils.converters import langchain_to_pydantic, token_count
from src.app.utils.logger import get_logger

from langchain_core.runnables.config import RunnableConfig

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Graph State
# ------------------------------------------------------------------
# -------------------------main wrapper graph state------------------
class WrapperState(BaseModel):
    messages_buffer: list[AnyMessage]
    ctx: str = ""


# --------------------------feedback worker graph state--------------
class FeedbackState(BaseModel):
    messages_buffer: list[AnyMessage]
    last_worker_output: WorkerResult | None = None
    id: int = 0
    static_ctx: str = ""
    dynamic_ctx: str = ""
    retry_loop: int = 0
    grade: Literal["pass", "revision_needed"] | None = None


# -------------------------Planner graph state-----------------------
class PlannerState(BaseModel):
    tasks: list[ExecutionStep] = []
    gathered_context: str = ""
    messages_buffer: list[AnyMessage] = []


# --------------------------State nodes------------------------------
# ------------------------------------------------------------------
# 2. Utility: static snapshot
# ------------------------------------------------------------------
async def build_static() -> str:
    files = await get_non_ignored_files()
    desc = await process_file(files)
    return "\n".join(f"- {f.file_path}: {f.description}" for f in desc)


def feedback_router(state: FeedbackState) -> Literal[Route.CODE, Route.END]:
    return Route.END if state.grade == "pass" else Route.CODE


def get_event_queue_from_config(config: RunnableConfig) -> asyncio.Queue:
    """
    Safely retrieves the asyncio.Queue from the RunnableConfig.

    Args:
        config: The RunnableConfig passed to the LangGraph node.

    Returns:
        The event queue instance.

    Raises:
        ValueError: If the event queue is not found or is of the wrong type.
    """
    metadata = config.get("metadata", {})
    event_queue = metadata.get("event_queue")

    if not isinstance(event_queue, asyncio.Queue):
        raise ValueError(
            "An 'event_queue' of type asyncio.Queue was not found in the "
            "RunnableConfig's metadata. Please ensure it is passed correctly."
        )

    return cast(asyncio.Queue, event_queue)


# ------------------------------------------------------------------
# 3. Core nodes
# ------------------------------------------------------------------
# ---------------------------subgraphs nodes------------------------
async def worker_feedback_subgraph_start(
    state: WrapperState | PlannerState, config: RunnableConfig
):
    logger.debug("Worker feedback subgraph start")
    if isinstance(state, WrapperState):
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
    elif isinstance(state, PlannerState):
        gathered_work_done = ""
        for task in state.tasks:
            init_messate = f"""
            ## Task description
            {task.description}
            ---
            ## Task guidelines
            Please follow the guidelines below to complete the task:
            {"\n".join(f"{guideline}" for guideline in task.guidelines)}
           
            ## Dependencies
            You will focuse on {task.target_ressource} and its dependencies. 
            Pay attention to the following files and their dependencies:
            {task.file_dependencies}
            
            ## Final notes
            You are working in a large project and you are not aware of the full project. 
            To help you avoid mistakes that could impact the rest of the project, I will provide you with the following notes:
            {"\n".join(f"{pitfall}" for pitfall in task.pitfalls)}
            """
            worker_state = FeedbackState(
                messages_buffer=[HumanMessage(init_messate)],
                id=task.task_id,
            )
            start_worker_graph = await worker_feedback_subgraph.ainvoke(
                worker_state, config=config
            )
            parse_worker_graph = FeedbackState(**start_worker_graph)
            proper_output = f"""
                For the task {task.task_id}, here is an overview of the changes I made:
                {parse_worker_graph.messages_buffer[-1].content}
                ---
                """
            gathered_work_done += proper_output + "\n"
        return {
            "messages_buffer": state.messages_buffer + [AIMessage(gathered_work_done)]
        }


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
async def give_feedback_node(state: FeedbackState, config: RunnableConfig):
    prompt_construction = f"""
    The task to be done and evaluate is:
    {state.messages_buffer[0].content}
    ---
    Here is the work done that should answer the task:
    {state.messages_buffer[-1].content}
    """
    tokens = token_count(prompt_construction)
    logger.debug(f"Evaluator of {tokens} tokens for {prompt_construction}")
    eval = None
    event_queue = get_event_queue_from_config(config)

    async for item in run_agent_with_events(
        evaluator_agent,
        prompt_construction,
        deps=AgentDeps(run_id=str(config.get("run_id", uuid.uuid4().hex))),
    ):
        await event_queue.put(item)
        if isinstance(item, Evaluation):
            eval = item

    if eval is None:
        raise RuntimeError("Evaluator agent did not return a result")
    if eval.grade == "pass":
        return {"messages_buffer": state.messages_buffer, "grade": "pass"}
    else:
        feedback_construction = f"""
        This is my feedback on your work:
        {eval.complete_feedback.feedback}
        ## Some good points
        {"\n".join(f"{good}" for good in eval.complete_feedback.strengths)}
        ## Some bad points
        {"\n".join(f"{bad}" for bad in eval.complete_feedback.weaknesses)}
        ## what you need to do to improve
        {eval.suggested_revision}
        ## Alternative approach
        If for some reason you can't to do the suggested revision, you can try the following alternative approach:
        {eval.alternative_approach}
        """
        return {
            "messages_buffer": state.messages_buffer
            + [HumanMessage(feedback_construction)],
            "retry_loop": state.retry_loop + 1,
            "grade": "revision_needed",
        }


async def router_node(
    state: WrapperState, config: RunnableConfig
) -> Literal[Route.CHAT, Route.CONTEXT, Route.PLAN, Route.CODE]:
    logger.debug(f"Task classification agent for {state.messages_buffer[-1].content}")
    e = None
    event_queue = get_event_queue_from_config(config)
    async for item in run_agent_with_events(
        task_classification_agent,
        str(state.messages_buffer[-1].content),
        deps=AgentDeps(run_id=str(config.get("run_id", uuid.uuid4().hex))),
    ):
        await event_queue.put(item)

        if isinstance(item, TaskType):
            e = item
    if e is None:
        raise RuntimeError("Task classification agent did not return a result")

    return e.task_type


async def worker_node(state: FeedbackState, config: RunnableConfig):
    openai_dicts = langchain_to_pydantic(state.messages_buffer[:-1])
    prompt = f"""
    ## Context to keep in mind
    {state.dynamic_ctx}
    --- 
    ## Task
    {state.messages_buffer[0].content}
    """
    prompt += (
        f"\n\n---\n\nLatest feedback: {state.messages_buffer[-1].content}"
        if state.retry_loop > 0
        else ""
    )
    tokens = token_count(prompt)
    logger.debug(f"Coding agent of {tokens} agent for {prompt}")
    worker_call = None
    async for run in run_agent_with_events(
        coding_agent,
        prompt,
        message_history=openai_dicts,
        deps=AgentDeps(run_id=str(config.get("run_id", uuid.uuid4().hex))),
    ):
        if isinstance(run, WorkerResult):
            worker_call = run

    if worker_call is None:
        raise RuntimeError("Worker agent did not return a result")

    file_details_parts = []
    if worker_call.files_to_edit:
        for file_edit in worker_call.files_to_edit:
            operation = file_edit.operation_type or "unknown"
            path = file_edit.file_path or "not specified"
            diff_content = file_edit.diff or "No diff available."
            detail = f"I made the {operation} operation following changes to the file {path}:\n{diff_content}"
            file_details_parts.append(detail)
    else:
        file_details_parts.append("No files were edited.")
    file_details_str = "\n\n---\n\n".join(file_details_parts)
    structured_output = f"""
    ## Summary of the changes I made:
    {worker_call.summary}
    ## Thought process
    ### Reasoning
    {worker_call.reasoning_logic.description}
    ### Steps I took
    {worker_call.reasoning_logic.steps}
    ## Personnal review of my work
    {worker_call.self_review}
    ## Details of the changes
    
    {file_details_str}
    
    """
    return {
        "messages_buffer": state.messages_buffer + [AIMessage(structured_output)],
        "dynamic_ctx": state.dynamic_ctx + ("\n\n---\n\n" + worker_call.research_notes)
        if worker_call.research_notes
        else "",
    }


async def approval_edit_node(state: FeedbackState, config: RunnableConfig):
    if state.last_worker_output is None:
        return
    if len(state.last_worker_output.files_to_edit) == 0:
        return

    modifications = []
    for file_edit in state.last_worker_output.files_to_edit:
        modifications.append(
            {
                "file_path": file_edit.file_path,
                "operation_type": file_edit.operation_type,
                "diff": file_edit.diff,
            }
        )

    approval_edit = interrupt({"type": Interraction.APPROVAL, "payload": modifications})

    if approval_edit == "approved":
        return Command(goto=END)
    else:
        return Command(goto=Route.USERFEEDBACK)


async def user_feedback_node(
    state: PlannerState | FeedbackState, config: RunnableConfig
):
    feedback = interrupt(
        {
            "type": Interraction.FEEDBACK,
        }
    )

    if isinstance(state, PlannerState):
        return Command(
            update={
                "messages_buffer": state.messages_buffer + [HumanMessage(feedback)]
            },
            goto=Route.PLAN,
        )

    elif isinstance(state, FeedbackState):
        return Command(
            update={
                "messages_buffer": state.messages_buffer + [HumanMessage(feedback)]
            },
            goto=Route.CODE,
        )


async def context_node(state: WrapperState, config: RunnableConfig):
    openai_dicts = langchain_to_pydantic(state.messages_buffer[:-1])
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
        deps=AgentDeps(run_id=str(config.get("run_id", uuid.uuid4().hex))),
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


async def plan_node(state: PlannerState, config: RunnableConfig):
    openai_dicts = langchain_to_pydantic(state.messages_buffer[:-1])
    prompt = f"""
    ## Context gathered so far
    {state.gathered_context}
    --- 
    ## User requested task
    {state.messages_buffer[-1].content}
    Plan the changes to be made
    """

    tokens = token_count(prompt)
    logger.debug(f"plan retriever agent of {tokens} tokens for prompt: {prompt}")
    steps = []
    async for run in run_agent_with_events(
        orchestrator_agent,
        prompt,
        message_history=openai_dicts,
        deps=AgentDeps(run_id=str(config.get("run_id", uuid.uuid4().hex))),
    ):
        if isinstance(run, ProjectPlan):
            steps = run.steps

    return {"tasks": steps}


async def chat_node(state: WrapperState, config: RunnableConfig):
    openai_dicts = langchain_to_pydantic(state.messages_buffer[:-1])
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
        deps=AgentDeps(run_id=str(config.get("run_id", uuid.uuid4().hex))),
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
checkpointer = InMemorySaver()


wrapper_graph = (
    StateGraph(WrapperState)
    .add_node(Route.CHAT, chat_node)
    .add_node(
        Route.CONTEXT,
        context_node,
    )
    .add_node(Route.PLAN, heavy_subgraph_start)
    .add_node(Route.CODE, worker_feedback_subgraph_start)
    .add_conditional_edges(START, router_node)
    .add_edge(Route.CONTEXT, Route.PLAN)
    .add_edge(Route.CHAT, END)
    .add_edge(Route.PLAN, END)
    .add_edge(Route.CODE, END)  # Add missing edge
).compile(checkpointer=checkpointer)

worker_feedback_subgraph = (
    StateGraph(FeedbackState)
    .add_node(Route.CODE, worker_node)
    .add_node(Route.FEEDBACK, give_feedback_node)
    .add_edge(START, Route.CODE)
    .add_edge(Route.CODE, Route.FEEDBACK)
    .add_conditional_edges(Route.FEEDBACK, feedback_router)
).compile(checkpointer=checkpointer)

heavy_subgraph = (
    StateGraph(PlannerState)
    .add_node(Route.PLAN, plan_node)
    .add_node(
        Route.CODE,
        worker_feedback_subgraph_start,
    )
    .add_edge(START, Route.PLAN)
    .add_edge(Route.PLAN, Route.CODE)
    .add_edge(Route.CODE, END)
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
    """
    Execute the main workflow graph with unified event orchestration.
    This function emits workflow-level events while agents emit their own
    detailed AG-UI events via run_agent_safe. All events flow through the
    unified event system for consistent frontend consumption.
    """
    event_queue: asyncio.Queue[str | dict | None] = asyncio.Queue()

    try:
        project_context = await build_static()
        initial_state = WrapperState(
            messages_buffer=[HumanMessage(content=prompt)],
            ctx=f"""
### Project structure:  
{project_context}
---
            """,
        )
        config: RunnableConfig = {
            "configurable": {"thread_id": conversation_id},
            "run_id": conversation_id,
            "metadata": {
                "thread_id": thread_id,
                "event_queue": event_queue,
            },
        }

        async def graph_runner():
            """
            Drives the graph execution and crucially, puts the graph's
            own streamed updates onto the shared event queue.
            """
            try:
                async for streamed_item in wrapper_graph.astream(
                    initial_state,
                    config=config,
                    stream_mode="updates",
                    subgraphs=True,
                ):
                    await event_queue.put(streamed_item)
            finally:
                await event_queue.put(None)

        await asyncio.gather(
            graph_runner(), inspect_and_log_events(event_queue, "raw_events.log")
        )
        logger.info("Main graph inspection run complete.")

    except Exception as e:
        logger.error(f"An error occurred during graph execution: {e}", exc_info=True)
        await event_queue.put(None)
        raise e


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
