import uuid
import asyncio
from typing import Tuple
from ag_ui.core.events import (
    EventType,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
)
from ag_ui.encoder import EventEncoder

EVENTS_QUEUE: asyncio.Queue[tuple[str, str]] = asyncio.Queue()


async def send_event(run_id: str, event_json: str):
    await EVENTS_QUEUE.put((run_id, event_json))


def emit_text_message_start() -> Tuple[TextMessageStartEvent, str]:
    """
    Return (event, message_id). message_id is returned for the caller
    to be able to reference the message in subsequent events.
    """
    message_id = uuid.uuid4().hex
    ev = TextMessageStartEvent(
        type=EventType.TEXT_MESSAGE_START,
        message_id=message_id,
        role="assistant",  # must be literal "assistant"
    )
    return ev, message_id


def emit_text_message_content(message_id: str, text: str) -> TextMessageContentEvent:
    return TextMessageContentEvent(
        type=EventType.TEXT_MESSAGE_CONTENT,
        message_id=message_id,
        delta=text,  # must be string
    )


def emit_text_message_end(message_id: str) -> TextMessageEndEvent:
    return TextMessageEndEvent(
        type=EventType.TEXT_MESSAGE_END,
        message_id=message_id,
    )


def emit_tool_call_start(tool_name: str) -> Tuple[ToolCallStartEvent, str]:
    """
    Return (event, tool_call_id). The tool_call_id is needed so the caller
    can later send args/end/result referring to this id.
    """
    tool_call_id = uuid.uuid4().hex
    ev = ToolCallStartEvent(
        type=EventType.TOOL_CALL_START,
        tool_call_id=tool_call_id,
        tool_call_name=tool_name,
    )
    return ev, tool_call_id


def emit_tool_call_args(tool_call_id: str, args_text: str) -> ToolCallArgsEvent:
    """
    args_text must be a string (serialize dicts to JSON/text before calling).
    """
    return ToolCallArgsEvent(
        type=EventType.TOOL_CALL_ARGS,
        tool_call_id=tool_call_id,
        delta=args_text,
    )


def emit_tool_call_end(tool_call_id: str) -> ToolCallEndEvent:
    return ToolCallEndEvent(
        type=EventType.TOOL_CALL_END,
        tool_call_id=tool_call_id,
    )


def emit_tool_call_result(
    message_id: str, tool_call_id: str, content: str
) -> ToolCallResultEvent:
    """
    message_id: the message this tool result is associated with (generate a new one if needed).
    content: string representation of result (serialize dicts to JSON strings).
    """
    return ToolCallResultEvent(
        type=EventType.TOOL_CALL_RESULT,
        message_id=message_id,
        tool_call_id=tool_call_id,
        content=content,
        role="tool",
    )


def encode_event(event) -> str:
    """
    Serialize the AG-UI Pydantic event to the wire format (string).
    EventEncoder.encode returns a string (JSON).
    """
    encoder = EventEncoder()
    return encoder.encode(event)
