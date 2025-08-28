from pydantic import BaseModel, Field
from litellm.types.utils import ChatCompletionMessageToolCall, Message

from langgraph.graph import END
from enum import Enum


class FinishReason(Enum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    FUNCTION_CALL = "function_call"
    ERROR = "error"
    INITIAL = "initial"


class NodeName(Enum):
    ENTRY = "entry"
    TOOL_CALL = "tool_call"
    STRUCTURE_OUTPUT = "structure_output"
    ERROR_HANDLER = "error_handler"


ROUTING = {
    FinishReason.TOOL_CALLS: NodeName.TOOL_CALL.value,
    FinishReason.FUNCTION_CALL: NodeName.TOOL_CALL.value,
    FinishReason.STOP: NodeName.STRUCTURE_OUTPUT.value,
    FinishReason.LENGTH: END,
    FinishReason.CONTENT_FILTER: END,
    FinishReason.ERROR: END,
}


class Tokens(BaseModel):
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cached_output_tokens: int = 0


class AgentGraph(BaseModel):
    message_history: list[Message] = Field(default_factory=list)
    tokens: Tokens = Field(default_factory=Tokens)
    tool_calls: list[ChatCompletionMessageToolCall] = Field(default_factory=list)
    tool_used: list[str] = Field(default_factory=list)
    finish_reason: FinishReason = Field(default=FinishReason.INITIAL)
    final_answer: str = Field(default="")
