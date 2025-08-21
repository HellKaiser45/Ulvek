from pydantic import BaseModel, Field
from langchain_core.messages import AnyMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.app.agents.schemas import FilePlan, ExecutionStep, Evaluation


checkpointer = InMemorySaver()


# -------------------------main wrapper graph state------------------
class WrapperState(BaseModel):
    messages_buffer: list[AnyMessage]
    ctx: list[str] = Field(default_factory=list)
    ctx_retry: int = 0


# --------------------------feedback worker graph state--------------
class FeedbackState(BaseModel):
    messages_buffer: list[AnyMessage]
    feedbacks: list[Evaluation] = Field(default_factory=list)
    last_worker_output: FilePlan | None = None
    id: int = 0
    static_ctx: str = ""
    dynamic_ctx: str = ""
    retry_loop: int = 0


# -------------------------Planner graph state-----------------------
class PlannerState(BaseModel):
    tasks: list[ExecutionStep] = []
    gathered_context: str = ""
    messages_buffer: list[AnyMessage] = []
