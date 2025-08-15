from pydantic import BaseModel
from typing import Literal
from langchain_core.messages import AnyMessage
from src.app.agents.schemas import WorkerResult, ExecutionStep

from langgraph.checkpoint.memory import InMemorySaver
from enum import StrEnum


checkpointer = InMemorySaver()


class Route(StrEnum):
    CHAT = "chat"
    CONTEXT = "context"
    PLAN = "plan"
    FEEDBACK = "feedback"
    CODE = "code"
    USERFEEDBACK = "user_feedback"
    USER_APPROVAL = "user_approval"
    END = "__end__"


class Interraction(StrEnum):
    APPROVAL = "approval"
    FEEDBACK = "feedback"
    INTOOLFEEDBACK = "intool_feedback"


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
