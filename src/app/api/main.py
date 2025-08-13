# agui_server.py
import asyncio
import json
import uuid
from typing import AsyncIterator
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from src.app.workflow.graph import run_main_graph
from src.app.utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="Ulvek API")


# ----------------------------------------------------------
# 1.  In-memory queues
# ----------------------------------------------------------

CONV_QUEUES: dict[str, asyncio.Queue[str]] = {}


# ----------------------------------------------------------
# 2.  Start a run
# ----------------------------------------------------------


@app.post("/start")
async def start_run(prompt: str) -> dict[str, str]:
    conv_id = uuid.uuid4()
    CONV_QUEUES[str(conv_id)] = asyncio.Queue()
    asyncio.create_task(run_main_graph(prompt, conversation_id=conv_id))
    return {"conversation_id": str(conv_id)}


# ----------------------------------------------------------
# 3.  SSE stream of AG-UI events
# ----------------------------------------------------------
@app.get("/stream/{conv_id}")
async def stream_events(conv_id: str) -> StreamingResponse:
    if conv_id not in CONV_QUEUES:
        raise HTTPException(status_code=404, detail="conversation not found")

    async def event_source() -> AsyncIterator[str]:
        q = CONV_QUEUES[conv_id]
        try:
            while True:
                payload: str = await q.get()
                yield f"data: {payload}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ----------------------------------------------------------
# 4.  POST endpoint for human answers
# ----------------------------------------------------------
@app.post("/answer/{conv_id}")
async def post_answer(conv_id: str, body: dict) -> dict[str, str]:
    """
    body = {"type":"custom","name":"userInput","value":{"text":"..."}}
    """
    q = CONV_QUEUES.get(conv_id)
    if not q:
        raise HTTPException(status_code=404, detail="conversation not found")

    await q.put(json.dumps(body))
    return {"status": "ok"}


# ----------------------------------------------------------
# 5.  Glue inside run_main_graph
# ----------------------------------------------------------


def make_sender(conv_id: str):
    async def _sender(event_json: str) -> None:
        q = CONV_QUEUES.get(conv_id)
        if q:
            await q.put(event_json)

    return _sender
