from src.app.workflow.types import (
    PlannerState,
    FeedbackState,
    checkpointer,
)
from src.app.workflow.enums import PlannerRoutes, Interraction
from src.app.utils.converters import (
    convert_langgraph_to_openai_messages,
    convert_openai_to_pydantic_messages,
    token_count,
)
from src.app.workflow.utils import get_event_queue_from_config
from langgraph.types import Command, interrupt
from langgraph.graph import START, END, StateGraph

from src.app.workflow.subgraphs.coding_workflow import worker_feedback_subgraph
from langchain_core.runnables.config import RunnableConfig
from langchain_core.messages import HumanMessage, AIMessage
from src.app.agents.agent import orchestrator_agent, run_agent_with_events
from src.app.agents.schemas import ProjectPlan

from src.app.utils.logger import get_logger

logger = get_logger(__name__)


# -----------------------subgraphs nodes------------------------
async def worker_feedback_subgraph_start(state: PlannerState, config: RunnableConfig):
    logger.debug("Worker feedback subgraph start from the PlannerState")
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
        You will focuse on {task.target_resource} and its dependencies. 
        Pay attention to the following files and their dependencies:
        {task.file_dependencies}
        
        ## Final notes
        You are working in a large project and you are not aware of the full project. 
        To help you avoid mistakes that could impact the rest of the project, I will provide you with the following notes:
        {"\n".join(f"{pitfall}" for pitfall in task.pitfalls)}
        """

        worker_state = FeedbackState(
            messages_buffer=[HumanMessage(init_messate)],
            static_ctx=state.gathered_context,
            id=task.task_id,
        )

        thread_id_from_config = config.get("configurable", {}).get("thread_id")
        original_configurable = config.get("configurable", {})

        new_configurable = {
            **original_configurable,
            "thread_id": f"{thread_id_from_config}_{task.task_id}",
        }

        updated_config: RunnableConfig = {**config, "configurable": new_configurable}
        start_worker_graph = await worker_feedback_subgraph.ainvoke(
            worker_state, config=updated_config
        )
        parse_worker_graph = FeedbackState(**start_worker_graph)
        proper_output = f"""
            For the task {task.task_id}, here is an overview of the changes I made:
            {parse_worker_graph.messages_buffer[-1].content}
            ---
            """
        gathered_work_done += proper_output + "\n"
    return {"messages_buffer": state.messages_buffer + [AIMessage(gathered_work_done)]}


# ----------------------Nodes--------------------------------------


async def plan_node(state: PlannerState, config: RunnableConfig):
    openai_dicts = []
    logger.debug("Plan node")
    if len(state.messages_buffer) == 1:
        prompt = f"""
        ## Context gathered so far
        {state.gathered_context}
        --- 
        ## User requested task
        {state.messages_buffer[0].content}
        Plan the changes to be made
        """
    else:
        openai_dicts = convert_openai_to_pydantic_messages(
            convert_langgraph_to_openai_messages(state.messages_buffer[:-1])
        )

        prompt = str(state.messages_buffer[-1].content)

    tokens = token_count(prompt)
    logger.debug(f"plan retriever agent of {tokens} tokens for prompt: {prompt}")
    logger.debug(f"Planning for {prompt}")
    event_queue = get_event_queue_from_config(config)
    steps = []
    final_run = ""

    async for run in run_agent_with_events(
        orchestrator_agent, prompt, message_history=openai_dicts
    ):
        await event_queue.put(run)
        if isinstance(run, ProjectPlan):
            steps = run.steps
            final_run = run.model_dump_json()

    logger.debug(f"Planning finished: {steps}")

    return {
        "tasks": steps,
        "messages_buffer": state.messages_buffer + [AIMessage(final_run)],
    }


async def user_feedback_node(state: PlannerState, config: RunnableConfig):
    feedback = interrupt(
        {
            "type": Interraction.FEEDBACK,
        }
    )

    return Command(
        update={"messages_buffer": state.messages_buffer + [HumanMessage(feedback)]},
        goto=PlannerRoutes.PLAN,
    )


async def approval_plan_node(state: PlannerState, config: RunnableConfig):
    plan_approval = interrupt(
        {
            "type": Interraction.APPROVAL,
            "payload": state.tasks,
        }
    )
    logger.debug(f"Approval plan node: {plan_approval}")
    if plan_approval == "approved":
        return Command(goto=PlannerRoutes.CODE)

    return Command(goto=PlannerRoutes.USERFEEDBACK)


heavy_subgraph = (
    StateGraph(PlannerState)
    .add_node(PlannerRoutes.PLAN, plan_node)
    .add_node(PlannerRoutes.USERFEEDBACK, user_feedback_node)
    .add_node(PlannerRoutes.USER_APPROVAL, approval_plan_node)
    .add_node(
        PlannerRoutes.CODE,
        worker_feedback_subgraph_start,
    )
    .add_edge(START, PlannerRoutes.PLAN)
    .add_edge(PlannerRoutes.PLAN, PlannerRoutes.USER_APPROVAL)
    .add_edge(PlannerRoutes.CODE, END)
).compile(checkpointer=checkpointer)
