from pydantic import BaseModel
from langchain_core.messages import AnyMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.app.agents.schemas import WorkerResult, ExecutionStep


checkpointer = InMemorySaver()


# -------------------------main wrapper graph state------------------
class WrapperState(BaseModel):
    messages_buffer: list[AnyMessage]
    ctx: list[str] = []
    ctx_retry: int = 0


# --------------------------feedback worker graph state--------------
class FeedbackState(BaseModel):
    messages_buffer: list[AnyMessage]
    last_worker_output: WorkerResult | None = None
    id: int = 0
    static_ctx: str = ""
    dynamic_ctx: str = ""
    retry_loop: int = 0


# -------------------------Planner graph state-----------------------
class PlannerState(BaseModel):
    tasks: list[ExecutionStep] = []
    gathered_context: str = ""
    messages_buffer: list[AnyMessage] = []
