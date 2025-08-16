from src.app.workflow.types import FeedbackState, checkpointer
from src.app.workflow.enums import CodeRoutes, Interraction
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command, interrupt
from langgraph.graph import START, StateGraph, END
from src.app.agents.agent import run_agent_with_events, evaluator_agent, coding_agent
from langchain_core.runnables.config import RunnableConfig
from src.app.agents.schemas import Evaluation, WorkerResult
from src.app.tools.files_edit import edit_file, write_file, EditParams, WriteParams
from src.app.utils.converters import (
    token_count,
    convert_langgraph_to_openai_messages,
    convert_openai_to_pydantic_messages,
)

from src.app.workflow.utils import get_event_queue_from_config
from src.app.utils.logger import get_logger
from textwrap import dedent


logger = get_logger(__name__)


async def user_feedback_node(state: FeedbackState, config: RunnableConfig):
    feedback = interrupt(
        {
            "type": Interraction.FEEDBACK,
        }
    )

    return Command(
        update={"messages_buffer": state.messages_buffer + [HumanMessage(feedback)]},
        goto=CodeRoutes.CODE,
    )


async def apply_edit_node(state: FeedbackState, config: RunnableConfig):
    assert state.last_worker_output is not None, (
        "apply_edit_node called without worker output - check workflow routing"
    )

    assert state.last_worker_output.files_to_edit, (
        "apply_edit_node called with no files to edit - check conditional logic"
    )

    for file_edit in state.last_worker_output.files_to_edit:
        match file_edit.operation_type:
            case "edit":
                assert file_edit.new_content is not None, (
                    "apply_edit_node called with create operation without new content - check conditional logic"
                )
                assert file_edit.old_content is not None, (
                    "apply_edit_node called with create operation with old content - check conditional logic"
                )

                await edit_file(
                    EditParams(
                        file_path=file_edit.file_path,
                        old=file_edit.old_content,
                        new=file_edit.new_content,
                    )
                )
            case "create":
                assert file_edit.new_content is not None, (
                    "apply_edit_node called with create operation without new content - check conditional logic"
                )
                await write_file(
                    WriteParams(
                        file_path=file_edit.file_path, content=file_edit.new_content
                    )
                )
            case "delete":
                assert file_edit.old_content is not None, (
                    "apply_edit_node called with delete operation without old content - check conditional logic"
                )
                await edit_file(
                    EditParams(
                        file_path=file_edit.file_path, old=file_edit.old_content, new=""
                    )
                )

    return


async def give_feedback_node(state: FeedbackState, config: RunnableConfig):
    prompt_construction = f"""
    The task to be done and evaluate is:
    {state.messages_buffer[0].content}
    ---
    Here is the work done that should answer the task:
    {state.messages_buffer[-1].content}
    """
    messages_history = (
        len(state.messages_buffer) > 2
        and convert_openai_to_pydantic_messages(
            convert_langgraph_to_openai_messages(state.messages_buffer[1:-1])
        )
    ) or None
    tokens = token_count(prompt_construction)
    logger.debug(f"Evaluator of {tokens} tokens for {prompt_construction}")
    eval = None
    event_queue = get_event_queue_from_config(config)

    async for item in run_agent_with_events(
        evaluator_agent,
        prompt_construction,
        message_history=messages_history,
    ):
        await event_queue.put(item)
        if isinstance(item, Evaluation):
            eval = item

    if eval is None:
        raise RuntimeError("Evaluator agent did not return a result")
    if eval.grade == "pass":
        return Command(
            goto=CodeRoutes.USER_APPROVAL,
            update={"messages_buffer": state.messages_buffer},
        )
    else:
        feedback_construction = dedent(f"""
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
        """)
        return Command(
            goto=CodeRoutes.CODE,
            update={
                "messages_buffer": state.messages_buffer
                + [HumanMessage(feedback_construction)],
                "retry_loop": state.retry_loop + 1,
            },
        )


async def worker_node(state: FeedbackState, config: RunnableConfig):
    openai_dicts = convert_openai_to_pydantic_messages(
        convert_langgraph_to_openai_messages(state.messages_buffer[:-1])
    )
    prompt = f"""
    ## Context to keep in mind
    {state.dynamic_ctx}
    --- 
    ## Task
    {state.messages_buffer[0].content}
    """
    prompt += (
        (f"\n\n---\n\nLatest feedback: {state.messages_buffer[-1].content}")
        if state.retry_loop > 0
        else ""
    )
    tokens = token_count(prompt)
    logger.debug(f"Coding agent of {tokens} agent for {prompt}")
    queue = get_event_queue_from_config(config)
    worker_call = None
    async for run in run_agent_with_events(
        coding_agent,
        prompt,
        message_history=openai_dicts,
    ):
        await queue.put(run)
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
        file_details_parts.append("No file to edit.")
    file_details_str = "\n\n---\n\n".join(file_details_parts)
    structured_output = dedent(f"""
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
    
    """)
    return {
        "messages_buffer": state.messages_buffer + [AIMessage(structured_output)],
        "last_worker_output": worker_call,
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
        return Command(goto=CodeRoutes.APPLYEDIT)
    else:
        return Command(goto=CodeRoutes.USERFEEDBACK)


worker_feedback_subgraph = (
    StateGraph(FeedbackState)
    .add_node(CodeRoutes.CODE, worker_node)
    .add_node(CodeRoutes.APPLYEDIT, apply_edit_node)
    .add_node(CodeRoutes.AGENTFEEDBACK, give_feedback_node)
    .add_node(CodeRoutes.USER_APPROVAL, approval_edit_node)
    .add_node(CodeRoutes.USERFEEDBACK, user_feedback_node)
    .add_edge(START, CodeRoutes.CODE)
    .add_edge(CodeRoutes.USER_APPROVAL, CodeRoutes.APPLYEDIT)
    .add_edge(CodeRoutes.USER_APPROVAL, CodeRoutes.USERFEEDBACK)
    .add_edge(CodeRoutes.USERFEEDBACK, CodeRoutes.CODE)
    .add_edge(CodeRoutes.APPLYEDIT, END)
    .add_edge(CodeRoutes.CODE, CodeRoutes.AGENTFEEDBACK)
    .add_edge(CodeRoutes.AGENTFEEDBACK, CodeRoutes.CODE)
    .add_edge(CodeRoutes.AGENTFEEDBACK, CodeRoutes.USER_APPROVAL)
).compile(checkpointer=checkpointer)
