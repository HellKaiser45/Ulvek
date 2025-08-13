import asyncio
import json
import uuid
from typing import AsyncIterator
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from src.app.workflow.graph import run_main_graph
from src.app.utils.frontends_adapters.interaction_manager import EVENTS_QUEUE

app = FastAPI(title="Ulvek API")


@app.post("/start")
async def start_run(prompt: str) -> dict[str, str]:
    conv_id = uuid.uuid4()
    asyncio.create_task(run_main_graph(prompt, conversation_id=conv_id))
    return {"conversation_id": str(conv_id)}


@app.get("/stream/{conv_id}")
async def stream_events(conv_id: str) -> StreamingResponse:
    async def event_source() -> AsyncIterator[str]:
        while True:
            cid, payload = await EVENTS_QUEUE.get()
            if cid == conv_id:
                yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/answer/{conv_id}")
async def post_answer(conv_id: str, body: dict) -> dict[str, str]:
    return {"status": "ok"}
