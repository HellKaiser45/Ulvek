import uuid
import asyncio
from enum import Enum
from typing import Any, Dict, Union
from dataclasses import dataclass
from datetime import datetime
from ag_ui.core.events import (
    EventType as AGUIEventType,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    CustomEvent,
)
from ag_ui.encoder import EventEncoder

from src.app.utils.logger import get_logger

logger = get_logger(__name__)

# Global event queue - all events flow through here
EVENTS_QUEUE: asyncio.Queue[tuple[str, str]] = asyncio.Queue()


class EventLevel(Enum):
    """Event hierarchy levels for proper separation of concerns."""

    WORKFLOW = "workflow"  # High-level workflow orchestration
    AGENT = "agent"  # Agent execution (handled by pydantic-ai)
    TOOL = "tool"  # Tool-specific events
    USER = "user"  # User interaction events


class WorkflowEventType(Enum):
    """Workflow-level event types."""

    STARTED = "workflow_started"
    NODE_EXECUTED = "node_executed"
    SUBGRAPH_ENTERED = "subgraph_entered"
    SUBGRAPH_EXITED = "subgraph_exited"
    COMPLETED = "workflow_completed"
    ERROR = "workflow_error"


@dataclass
class WorkflowEvent:
    """Structured workflow event that gets converted to AG-UI format."""

    type: WorkflowEventType
    conversation_id: str
    data: Dict[str, Any]
    timestamp: datetime | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_agui_text_event(
        self,
    ) -> tuple[TextMessageStartEvent, TextMessageContentEvent, TextMessageEndEvent]:
        """Convert workflow event to AG-UI text message events."""
        message_id = uuid.uuid4().hex
        content = self._format_content()
        start_event = TextMessageStartEvent(
            type=AGUIEventType.TEXT_MESSAGE_START,
            message_id=message_id,
            role="assistant",
        )
        content_event = TextMessageContentEvent(
            type=AGUIEventType.TEXT_MESSAGE_CONTENT,
            message_id=message_id,
            delta=content,
        )
        end_event = TextMessageEndEvent(
            type=AGUIEventType.TEXT_MESSAGE_END, message_id=message_id
        )
        return start_event, content_event, end_event

    def _format_content(self) -> str:
        """Format workflow event data into readable content."""
        t = self.type
        match t:
            case WorkflowEventType.STARTED:
                prompt = self.data.get("prompt", "Unknown task")
                return f"🚀 Starting workflow: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
            case WorkflowEventType.NODE_EXECUTED:
                namespace = self.data.get("namespace", "unknown")
                step = self.data.get("step", 0)
                return f"⚙️ Executed step {step} in {namespace}"
            case WorkflowEventType.SUBGRAPH_ENTERED:
                subgraph = self.data.get("subgraph_name", "unknown")
                return f"📊 Entering {subgraph} workflow"
            case WorkflowEventType.SUBGRAPH_EXITED:
                subgraph = self.data.get("subgraph_name", "unknown")
                return f"✅ Completed {subgraph} workflow"
            case WorkflowEventType.COMPLETED:
                steps = self.data.get("total_steps", 0)
                return f"🎉 Workflow completed successfully in {steps} steps"
            case WorkflowEventType.ERROR:
                error = self.data.get("error", "Unknown error")
                return f"❌ Workflow error: {error}"
            case _:
                return f"🔔 Workflow event: {t}"


# Union type for all possible events
EventUnion = Union[
    # AG-UI Events (from pydantic-ai and tools)
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    WorkflowEvent,
    CustomEvent,
]


class UnifiedEventManager:
    def __init__(self):
        self.encoder = EventEncoder()
        self._active_workflows: Dict[str, Dict[str, Any]] = {}

    async def emit_workflow_event(
        self, event_type: WorkflowEventType, conversation_id: str, data: Dict[str, Any]
    ) -> None:
        """Emit a workflow-level event."""
        event = WorkflowEvent(
            type=event_type, conversation_id=conversation_id, data=data
        )
        self._active_workflows.setdefault(conversation_id, {}).update(
            {"last_event": event_type.value, "last_update": event.timestamp, **data}
        )
        await self._send_workflow_event(event)

    async def sendworkflow_event(self, event: WorkflowEvent) -> None:
        start, content, end = event.to_agui_text_event()
        await self.emit_agui_event(start, event.conversation_id)
        await self.emit_agui_event(content, event.conversation_id)
        await self.emit_agui_event(end, event.conversation_id)
        logger.debug(
            f"Sent workflow event: {event.type.value} for {event.conversation_id}"
        )

    async def emit_agui_event(
        self,
        event: Union[
            TextMessageStartEvent,
            TextMessageContentEvent,
            TextMessageEndEvent,
            ToolCallStartEvent,
            ToolCallArgsEvent,
            ToolCallEndEvent,
            ToolCallResultEvent,
            CustomEvent,
        ],
        conversation_id: str,
    ) -> None:
        """Emit an AG-UI event directly."""
        event_json = self.encoder.encode(event)
        await EVENTS_QUEUE.put((conversation_id, event_json))

    async def _send_workflow_event(self, event: WorkflowEvent) -> None:
        """Convert workflow event to AG-UI format and send."""
        # For workflow events, we send them as text messages
        # This makes them visible in the CLI
        start, content, end = event.to_agui_text_event()

        # Send the sequence of events
        await self.emit_agui_event(start, event.conversation_id)
        await self.emit_agui_event(content, event.conversation_id)
        await self.emit_agui_event(end, event.conversation_id)

        logger.debug(
            f"Sent workflow event: {event.type.value} for {event.conversation_id}"
        )

    def get_workflow_state(self, conversation_id: str) -> Dict[str, Any]:
        """Get current workflow state for debugging."""
        return self._active_workflows.get(conversation_id, {})


# Global instance
event_manager = UnifiedEventManager()


# Convenience functions that match your existing API
async def emit_graph_event(
    conversation_id: str, event_type: str, data: Dict[str, Any]
) -> None:
    """
    Compatibility function for existing code.
    Maps string event types to enum values.
    """
    try:
        workflow_event_type = WorkflowEventType(event_type)
    except ValueError:
        logger.warning(f"Unknown event type: {event_type}, treating as generic")
        # Create a generic workflow event
        await event_manager.emit_workflow_event(
            WorkflowEventType.NODE_EXECUTED,  # Default fallback
            conversation_id,
            {"custom_type": event_type, **data},
        )
        return

    await event_manager.emit_workflow_event(workflow_event_type, conversation_id, data)


async def send_event(run_id: str, event_json: str) -> None:
    """Compatibility function for existing AG-UI event sending."""
    await EVENTS_QUEUE.put((run_id, event_json))


# Helper functions for tool/agent events (keeping your existing API)
def emit_text_message_start() -> tuple[TextMessageStartEvent, str]:
    """Return (event, message_id)."""
    message_id = uuid.uuid4().hex
    event = TextMessageStartEvent(
        type=AGUIEventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant"
    )
    return event, message_id


def emit_text_message_content(message_id: str, text: str) -> TextMessageContentEvent:
    return TextMessageContentEvent(
        type=AGUIEventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=text
    )


def emit_text_message_end(message_id: str) -> TextMessageEndEvent:
    return TextMessageEndEvent(
        type=AGUIEventType.TEXT_MESSAGE_END, message_id=message_id
    )


def emit_tool_call_start(tool_name: str) -> tuple[ToolCallStartEvent, str]:
    """Return (event, tool_call_id)."""
    tool_call_id = uuid.uuid4().hex
    event = ToolCallStartEvent(
        type=AGUIEventType.TOOL_CALL_START,
        tool_call_id=tool_call_id,
        tool_call_name=tool_name,
    )
    return event, tool_call_id


def emit_tool_call_args(tool_call_id: str, args_text: str) -> ToolCallArgsEvent:
    return ToolCallArgsEvent(
        type=AGUIEventType.TOOL_CALL_ARGS, tool_call_id=tool_call_id, delta=args_text
    )


def emit_tool_call_end(tool_call_id: str) -> ToolCallEndEvent:
    return ToolCallEndEvent(type=AGUIEventType.TOOL_CALL_END, tool_call_id=tool_call_id)


def emit_tool_call_result(
    message_id: str, tool_call_id: str, content: str
) -> ToolCallResultEvent:
    return ToolCallResultEvent(
        type=AGUIEventType.TOOL_CALL_RESULT,
        message_id=message_id,
        tool_call_id=tool_call_id,
        content=content,
        role="tool",
    )


# For tools that need direct AG-UI event emission
async def send_agui_event(event, conversation_id: str) -> None:
    """Send AG-UI event directly through unified system."""
    await event_manager.emit_agui_event(event, conversation_id)


def emit_custom_event(name: str, value: dict) -> CustomEvent:
    """Creates a structured custom event."""
    return CustomEvent(
        type=AGUIEventType.CUSTOM,
        name=name,
        value=value,
    )


def encode_event(event) -> str:
    """Serialize AG-UI event to wire format."""
    encoder = EventEncoder()
    return encoder.encode(event)
