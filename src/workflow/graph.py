from __future__ import annotations

from pydantic import BaseModel
from typing import Literal
from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.memory import InMemorySaver
from src.agents.agent import (
    orchestrator_agent,
    coding_agent,
    evaluator_agent,
    context_retriever_agent,
    conversational_agent,
    task_classification_agent,
)
from src.agents.schemas import ExecutionStep, Route
from src.tools.codebase import process_file, get_non_ignored_files
from langchain_core.messages import HumanMessage, AIMessage, AnyMessage
from src.utils.converters import langchain_to_pydantic, token_count
from src.utils.logger import get_logger
from pydantic_ai import UnexpectedModelBehavior, capture_run_messages


checkpointer = InMemorySaver()
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
    id: int = 0
    static_ctx: str = ""
    dynamic_ctx: str = ""
    work_done: str = ""
    retry_loop: int = 0
    grade: Literal["pass", "revision_needed"] | None = None


# -------------------------Planner graph state-----------------------
class PlannerState(BaseModel):
    tasks: list[ExecutionStep] = []
    gathered_context: str = ""
    messages_buffer: list[AnyMessage] = []


# ------------------------------------------------------------------
# 2. Utility: static snapshot
# ------------------------------------------------------------------
async def build_static() -> str:
    files = await get_non_ignored_files()
    desc = await process_file(files)
    return "\n".join(f"- {f.file_path}: {f.description}" for f in desc)


def feedback_router(state: FeedbackState) -> Literal[Route.CODE, Route.END]:
    return Route.END if state.grade == "pass" else Route.CODE


# ------------------------------------------------------------------
# 3. Core nodes
# ------------------------------------------------------------------
# ---------------------------subgraphs nodes------------------------


async def worker_feedback_subgraph_start(state: WrapperState | PlannerState):
    logger.debug("Worker feedback subgraph start")

    if isinstance(state, WrapperState):
        worker_state = FeedbackState(
            messages_buffer=[state.messages_buffer[-1]],
            static_ctx=state.ctx,
        )
        logger.debug(f"Worker feedback subgraph start: {worker_state}")
        start_worker_graph = await worker_feedback_subgraph.ainvoke(worker_state)
        parse_worker_graph = FeedbackState(**start_worker_graph)

        proper_output = f"""
        Here is an overview of the changes I made:
        {parse_worker_graph.work_done}
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
            start_worker_graph = await worker_feedback_subgraph.ainvoke(worker_state)
            parse_worker_graph = FeedbackState(**start_worker_graph)

            proper_output = f"""
                For the task {task.task_id}, here is an overview of the changes I made:

                {parse_worker_graph.work_done}
                ---
                """
            gathered_work_done += proper_output + "\n"
        return {
            "messages_buffer": state.messages_buffer + [AIMessage(gathered_work_done)]
        }


async def heavy_subgraph_start(state: WrapperState):
    heavy_state = PlannerState(
        gathered_context=state.ctx,
        messages_buffer=[state.messages_buffer[-1]],
    )
    heavy_graph = await heavy_subgraph.ainvoke(heavy_state)
    parse_heavy_graph = PlannerState(**heavy_graph)

    return {
        "messages_buffer": state.messages_buffer
        + [AIMessage(parse_heavy_graph.gathered_context)]
    }


# ----------------------------nodes---------------------------------
async def give_feedback_node(state: FeedbackState):
    prompt_construction = f"""
    The task to be done and evaluate is:
    {state.messages_buffer[0].content}
    ---
    Here is the work done that should answer the task:
    {state.messages_buffer[-1].content}
    """

    tokens = token_count(prompt_construction)

    logger.debug(f"Evaluator of {tokens} agent for {prompt_construction}")
    eval = None
    with capture_run_messages() as messages:
        try:
            eval = (await evaluator_agent.run(prompt_construction)).output
        except UnexpectedModelBehavior as e:
            logger.error(f"Unexpected model behavior error: {e}")
            logger.debug(f"cause of the error: {e.__cause__}")
            logger.debug(f"meessages: {messages}")
    if eval:
        if eval.grade == "pass":
            return {"messages_buffer": state.messages_buffer}

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
            }


async def router_node(
    state: WrapperState,
) -> Literal[Route.CHAT, Route.CONTEXT, Route.PLAN, Route.CODE]:
    logger.debug(f"Task classification agent for {state.messages_buffer[-1].content}")
    e = Route.CHAT
    with capture_run_messages() as messages:
        try:
            e = (
                await task_classification_agent.run(
                    str(state.messages_buffer[-1].content)
                )
            ).output
            return e.task_type
        except UnexpectedModelBehavior as error:
            logger.error(f"Unexpected model behavior error: {error}")
            logger.debug(f"cause of the error: {error.__cause__}")
            logger.debug(f"meessages: {messages}")
        logger.debug(f"Task classification agent result: {e}")
    return e


async def worker_node(state: FeedbackState):
    openai_dicts = langchain_to_pydantic(state.messages_buffer[:-1])
    prompt = f"""
    ## Context to keep in mind
    {state.dynamic_ctx}
    --- 
    ## Task
    {state.messages_buffer[-1].content}
    """
    tokens = token_count(prompt)

    logger.debug(f"Coding agent of {tokens} agent for {prompt}")

    worker_call = None
    with capture_run_messages() as messages:
        try:
            worker_call = (
                await coding_agent.run(prompt, message_history=openai_dicts)
            ).output
        except UnexpectedModelBehavior as e:
            logger.error(f"Unexpected model behavior error: {e}")
            logger.debug(f"cause of the error: {e.__cause__}")
            logger.debug(f"meessages: {messages}")
    if worker_call:
        file_details_parts = []
        if worker_call.files_edited:  # Check if the list exists and is not None/empty
            for file_edit in worker_call.files_edited:
                # Handle potential None values safely using 'or'
                operation = file_edit.operation_type or "unknown"
                path = file_edit.file_path or "not specified"
                diff_content = file_edit.diff or "No diff available."

                detail = f"I made the {operation} operation following changes to the file {path}:\n{diff_content}"
                file_details_parts.append(detail)
        else:
            file_details_parts.append("No files were edited.")

        file_details_str = "\n\n---\n\n".join(
            file_details_parts
        )  # Separating each file's details

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
            "dynamic_ctx": state.dynamic_ctx
            + ("\n\n---\n\n" + worker_call.research_notes)
            if worker_call.research_notes
            else "",
            "work_done": structured_output,
        }


async def context_node(state: WrapperState):
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
    with capture_run_messages() as messages:
        try:
            context_call = (
                await context_retriever_agent.run(prompt, message_history=openai_dicts)
            ).output
        except UnexpectedModelBehavior as e:
            logger.error(f"Unexpected model behavior error: {e}")
            logger.debug(f"cause of the error: {e.__cause__}")
            logger.debug(f"meessages: {messages}")

    if context_call:
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
                    t   itle: {ext.title}
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


async def plan_node(state: PlannerState):
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
    plan_call = None
    with capture_run_messages() as messages:
        try:
            plan_call = (
                await orchestrator_agent.run(prompt, message_history=openai_dicts)
            ).output
        except UnexpectedModelBehavior as e:
            logger.error(f"Unexpected model behavior error: {e}")
            logger.debug(f"cause of the error: {e.__cause__}")
            logger.debug(f"meessages: {messages}")
    if plan_call:
        return {"tasks": plan_call.steps}


async def chat_node(state: WrapperState):
    openai_dicts = langchain_to_pydantic(state.messages_buffer[:-1])
    prompt = f"""
    ## Context to keep in mind
    {state.ctx}
    --- 
    {state.messages_buffer[-1].content}
    """
    logger.info(f"Chat: {prompt}")
    tokens = token_count(prompt)
    logger.debug(f"chat retriever agent of {tokens} tokens for prompt: {prompt}")

    chat_call = None
    with capture_run_messages() as messages:
        try:
            chat_call = (
                await conversational_agent.run(prompt, message_history=openai_dicts)
            ).output
        except UnexpectedModelBehavior as e:
            logger.error(f"Unexpected model behavior error: {e}")
            logger.debug(f"cause of the error: {e.__cause__}")
            logger.debug(f"meessages: {messages}")

    if chat_call:
        return {
            "messages_buffer": state.messages_buffer + [AIMessage(chat_call)],
        }


# ------------------------------------------------------------------
# 4. Graphs construction
# ------------------------------------------------------------------
# -------------------------main wrapper graph state-----------------
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
).compile()

worker_feedback_subgraph = (
    StateGraph(FeedbackState)
    .add_node(Route.CODE, worker_node)
    .add_node(Route.FEEDBACK, give_feedback_node)
    .add_edge(START, Route.CODE)
    .add_edge(Route.CODE, Route.FEEDBACK)
    .add_conditional_edges(Route.FEEDBACK, feedback_router)
).compile()

heavy_subgraph = (
    StateGraph(PlannerState)
    .add_node(Route.PLAN, plan_node)
    .add_node(Route.CODE, worker_feedback_subgraph_start)
    .add_edge(START, Route.PLAN)
    .add_edge(Route.PLAN, Route.CODE)
    .add_edge(Route.CODE, END)
).compile()


# ------------------------------------------------------------------
# 5. Public API
# ------------------------------------------------------------------


async def run_agent(prompt: str) -> str:
    initial: WrapperState = WrapperState(messages_buffer=[HumanMessage(prompt)])
    out = await wrapper_graph.ainvoke(initial)
    parsed_out = WrapperState(**out)

    return str(parsed_out.messages_buffer[-1].content)
