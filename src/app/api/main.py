import asyncio
import uuid
from typing import AsyncIterator
from fastapi import FastAPI, Body, HTTPException, Request
from fastapi.responses import StreamingResponse
from src.app.workflow.graph import run_main_graph
from src.app.utils.frontends_adapters.interaction_manager import EVENTS_QUEUE
from src.app.utils.logger import get_logger
from sse_starlette.sse import EventSourceResponse
from typing import Any

logger = get_logger(__name__)

app = FastAPI(title="Ulvek API")

# Track active conversations for better debugging
active_conversations: dict[str, asyncio.Task] = {}


@app.post("/start")
async def start_run(prompt: str) -> dict[str, str]:
    conv_id = uuid.uuid4()
    conv_id_str = str(conv_id)

    # Create task with proper error handling
    task = asyncio.create_task(
        run_main_graph_with_cleanup(prompt, conv_id), name=f"conversation-{conv_id_str}"
    )

    # Track the task
    active_conversations[conv_id_str] = task

    logger.info(f"Started conversation {conv_id_str} with prompt: {prompt[:50]}...")

    return {"conversation_id": conv_id_str}


async def run_main_graph_with_cleanup(prompt: str, conversation_id: uuid.UUID) -> None:
    """Wrapper to handle task cleanup and error logging."""
    conv_id_str = str(conversation_id)
    try:
        await run_main_graph(prompt, conversation_id)
        logger.info(f"Successfully completed conversation {conv_id_str}")
    except Exception as e:
        logger.error(f"Error in conversation {conv_id_str}: {e}", exc_info=True)
        # Send error event to client
        try:
            from src.app.utils.frontends_adapters.interaction_manager import (
                event_manager,
                WorkflowEventType,
            )

            await event_manager.emit_workflow_event(
                WorkflowEventType.ERROR,
                conv_id_str,
                {"error": str(e), "error_type": type(e).__name__, "final_error": True},
            )
        except Exception as emit_error:
            logger.error(f"Failed to emit error event: {emit_error}")
    finally:
        # Clean up task tracking
        active_conversations.pop(conv_id_str, None)
        logger.debug(f"Cleaned up conversation {conv_id_str}")


@app.get("/stream/{conversation_id}")
async def stream_events(request: Request, conversation_id: str):
    """
    Connects a client to the event stream for a specific conversation.
    """
    logger.info(f"Starting event stream for conversation {conversation_id}")

    async def event_generator():
        # Use a local queue to avoid race conditions with the global one
        local_queue = asyncio.Queue()
        # Register this local queue to receive events for this conversation
        # This requires a modification to your event manager or a separate dispatcher
        # For simplicity here, we'll just pull from the global queue
        # A more robust solution would involve a pub/sub pattern

        while True:
            # Check if the client is still connected
            if await request.is_disconnected():
                logger.warning(
                    f"Client disconnected from conversation {conversation_id}"
                )
                break

            try:
                # Wait for an event from the global queue
                conv_id, event_json = await asyncio.wait_for(
                    EVENTS_QUEUE.get(), timeout=1.0
                )

                # Check if the event belongs to this conversation stream
                if str(conv_id) == str(conversation_id):
                    # THIS IS THE KEY CHANGE:
                    # Yield a dictionary. sse-starlette will format it correctly
                    # as "data: <json_string>\n\n"
                    yield {"data": event_json}
                else:
                    # If the event is not for this conversation, put it back
                    # This is a simple approach; a proper pub/sub system is better
                    await EVENTS_QUEUE.put((conv_id, event_json))
                    await asyncio.sleep(0.01)  # Avoid busy-waiting

            except asyncio.TimeoutError:
                # No event received, continue waiting
                continue
            except Exception as e:
                logger.error(f"Error in event stream: {e}")
                break

    return EventSourceResponse(event_generator())


@app.post("/answer/{conv_id}")
async def post_answer(conv_id: str, body: dict[str, Any] = Body(...)) -> dict[str, str]:
    """
    Receives user input from the frontend and puts it on the event queue.
    This is the critical fix for the interactive tool loop.
    """
    import json

    logger.debug(f"Received answer for conversation {conv_id}: {body}")

    # Check if conversation is still active
    if conv_id not in active_conversations:
        logger.warning(f"Received answer for inactive conversation {conv_id}")
        raise HTTPException(
            status_code=404, detail="Conversation not found or completed"
        )

    # The tool is waiting on the queue for an event with this conversation ID.
    # We must serialize the body back to a JSON string, as that's what the queue expects.
    payload = json.dumps(body)
    await EVENTS_QUEUE.put((conv_id, payload))

    logger.debug(f"Queued answer for conversation {conv_id}")
    return {"status": "ok"}


@app.get("/conversations")
async def list_conversations() -> dict[str, Any]:
    """Debug endpoint to see active conversations."""
    active = {}
    for conv_id, task in active_conversations.items():
        active[conv_id] = {
            "name": task.get_name(),
            "done": task.done(),
            "cancelled": task.cancelled(),
        }

    return {
        "active_conversations": active,
        "queue_size": EVENTS_QUEUE.qsize(),
    }


# Health check
@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "ulvek-api"}
