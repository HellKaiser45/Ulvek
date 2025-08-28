from src.app.workflow.types import FeedbackState, checkpointer
from src.app.workflow.enums import CodeRoutes, Interraction
from langchain_core.messages import HumanMessage
from langgraph.types import Command, interrupt
from langgraph.graph import START, StateGraph, END
from src.app.agents.agentlite import evaluator_agent, coding_agent
from langchain_core.runnables.config import RunnableConfig
from src.app.tools.file_operations import execute_file_plan
from src.app.utils.converters import (
    token_count,
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

    execute_file_plan(state.last_worker_output)

    return


async def give_feedback_node(state: FeedbackState, config: RunnableConfig):
    logger.debug("Give feedback node")
    assert state.last_worker_output is not None, (
        "give_feedback_node called without worker output - check workflow routing"
    )

    prompt_construction = f"""
    ## Task
    {state.messages_buffer[0].content}
    
    ## Proposed Changes
    {state.last_worker_output.model_dump_json()}

    Please provide your honest feedback on the proposed changes from the coding agent.

    """

    tokens = token_count(prompt_construction)
    logger.debug(f"Evaluator of {tokens} tokens for {prompt_construction[:100]}...")

    event_queue = get_event_queue_from_config(config)
    agent_result = await evaluator_agent.run(prompt_construction)
    assert not isinstance(agent_result, str), (
        "Evaluator agent did not return a valid result"
    )

    if agent_result.grade or state.retry_loop > 2:
        return Command(
            goto=CodeRoutes.USER_APPROVAL,
        )
    else:
        return Command(
            goto=CodeRoutes.CODE,
            update={
                "retry_loop": state.retry_loop + 1,
                "feedbacks": state.feedbacks + [agent_result],
            },
        )


async def worker_node(state: FeedbackState, config: RunnableConfig):
    logger.debug("Worker node")

    prompt = dedent(f"""
## Context Information
    {state.static_ctx}

## Original Task
    {state.messages_buffer[0].content}

    """)

    if len(state.feedbacks) > 0:
        prompt += f"""
        ## Feedback
        {state.feedbacks[-1].model_dump_json()}
        """

    tokens = token_count(prompt)
    logger.debug(f"Coding agent of {tokens} agent for {prompt[:100]}...")
    queue = get_event_queue_from_config(config)

    agent_result = await coding_agent.run(prompt)
    assert not isinstance(agent_result, str), (
        "Worker agent did not return a valid result"
    )

    return {
        "last_worker_output": agent_result,
    }


async def approval_edit_node(state: FeedbackState, config: RunnableConfig):
    modifications = []

    str_modifications = (
        state.last_worker_output.model_dump_json()
        if state.last_worker_output is not None
        else ""
    )
    logger.info(f"do you approve the following changes: {str_modifications}")

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
