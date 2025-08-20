from src.app.workflow.types import FeedbackState, checkpointer
from src.app.workflow.enums import CodeRoutes, Interraction
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command, interrupt
from langgraph.graph import START, StateGraph, END
from src.app.agents.agent import run_agent_with_events, evaluator_agent, coding_agent
from langchain_core.runnables.config import RunnableConfig
from src.app.agents.schemas import Evaluation, WorkerResult
from src.app.tools.files_edit import edit_file, write_file, add_to_file
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
                if (
                    file_edit.old_content is None
                    and file_edit.line_to_start_edit is not None
                ):
                    logger.debug(f"Adding to file {file_edit.file_path}")
                    await add_to_file(
                        file_path=file_edit.file_path,
                        new_content=file_edit.new_content,
                        line=file_edit.line_to_start_edit,
                    )
                else:
                    assert file_edit.old_content is not None, (
                        "apply_edit_node called with edit operation without old content - check conditional logic"
                    )
                    logger.debug(f"Editing file {file_edit.file_path}")
                    await edit_file(
                        file_path=file_edit.file_path,
                        old=file_edit.old_content,
                        new=file_edit.new_content,
                    )

            case "create":
                assert file_edit.new_content is not None, (
                    "apply_edit_node called with create operation without new content - check conditional logic"
                )
                logger.debug(f"Creating file {file_edit.file_path}")
                await write_file(
                    file_path=file_edit.file_path, content=file_edit.new_content
                )
            case "delete":
                assert file_edit.old_content is not None, (
                    "apply_edit_node called with delete operation without old content - check conditional logic"
                )
                logger.debug(f"Deleting file {file_edit.file_path}")
                await edit_file(
                    file_path=file_edit.file_path, old=file_edit.old_content, new=""
                )

    return


async def give_feedback_node(state: FeedbackState, config: RunnableConfig):
    logger.debug("Give feedback node")
    prompt_construction = f"""
    Please provide your honest feedback on the proposed changes from the coding agent.
    
    ## Context
    - These changes are PROPOSED only and have not been implemented yet
    - Evaluate based on the original codebase state, not assuming these changes are already applied
    - Focus on whether these proposed changes would solve the original task

    ## Previous Attempts (if any)
    Retry attempt: {state.retry_loop}

    """
    messages_history = convert_openai_to_pydantic_messages(
        convert_langgraph_to_openai_messages(state.messages_buffer)
    )

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
    elif eval.grade == "pass":
        return Command(
            goto=CodeRoutes.USER_APPROVAL,
        )
    else:
        feedback_construction = dedent(f"""
        This is my feedback on what you wanted to do:
        {eval.model_dump_json()}

        **Important:** The above proposed changes have NOT been implemented yet. 
        Please revise your approach based on this feedback and propose new changes.
        
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
    logger.debug("Worker node")

    if len(state.messages_buffer) == 1:
        prompt = f"""
        ## Context Information
        {state.static_ctx}
        
        ## Original Task
        {state.messages_buffer[0].content}
        
        ## Important Instructions
        - Propose NEW changes that build upon or modify the current state
        - Do NOT assume your previous proposals were implemented
        - Use your tools to read current file contents before proposing changes
        - Focus on incremental improvements based on feedback
        """
    else:
        prompt = str(state.messages_buffer[-1].content)

    openai_dicts = convert_openai_to_pydantic_messages(
        convert_langgraph_to_openai_messages(state.messages_buffer[:-1])
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

    structured_output = dedent(f"""
    {worker_call.model_dump_json()}
    **Note:** These changes are proposed and will be reviewed before implementation. 
    """)

    return {
        "messages_buffer": state.messages_buffer + [AIMessage(structured_output)],
        "last_worker_output": worker_call,
    }


async def approval_edit_node(state: FeedbackState, config: RunnableConfig):
    if state.last_worker_output is None:
        logger.debug("No worker output, skipping approval")
        return

    elif (
        state.last_worker_output.files_to_edit is not None
        and len(state.last_worker_output.files_to_edit) == 0
    ):
        logger.debug("No files to edit, skipping approval")

        return

    modifications = []

    for file_edit in state.last_worker_output.files_to_edit or []:
        modifications.append(
            {
                "file_path": file_edit.file_path,
                "operation_type": file_edit.operation_type,
                "diff": file_edit.diff,
            }
        )

    str_modifications = "\n".join(str(mod) for mod in modifications)

    logger.debug(f"do you approve the following changes: {str_modifications}")

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
    .add_edge(CodeRoutes.APPLYEDIT, END)
    .add_edge(CodeRoutes.CODE, CodeRoutes.AGENTFEEDBACK)
).compile(checkpointer=checkpointer)
