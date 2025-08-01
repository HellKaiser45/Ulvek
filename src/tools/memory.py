from src.config import config
from mem0 import Memory
import time
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


m = Memory.from_config(config)


class MemoryResult(BaseModel):
    """Individual memory result from Mem0 search"""

    id: str = Field(description="Unique identifier for the memory")
    memory: str = Field(description="The actual memory text content")
    user_id: str | None = Field(
        None, description="ID of the user associated with this memory"
    )
    agent_id: str | None = Field(
        None, description="ID of the agent associated with this memory"
    )
    app_id: str | None = Field(
        None, description="ID of the app associated with this memory"
    )
    run_id: str | None = Field(
        None, description="ID of the run/session associated with this memory"
    )
    hash: str | None = Field(None, description="Hash of the memory content")
    metadata: dict[str, Any] | None = Field(
        None, description="Additional metadata for the memory"
    )
    categories: list[str] | None = Field(
        None, description="Categories assigned to this memory"
    )
    score: float | None = Field(None, description="Relevance score for search results")
    created_at: datetime | None = Field(None, description="When the memory was created")
    updated_at: datetime | None = Field(
        None, description="When the memory was last updated"
    )
    immutable: bool | None = Field(
        None, description="Whether the memory can be modified"
    )
    expiration_date: datetime | None = Field(
        None, description="When the memory expires"
    )
    owner: str | None = Field(None, description="Owner of the memory")
    organization: str | None = Field(None, description="Organization ID")


class SearchResponse(BaseModel):
    """Complete search response from Mem0"""

    results: list[MemoryResult] = Field(description="List of memory results")


class PaginatedResponse(BaseModel):
    """Paginated response for get_all operations"""

    count: int = Field(description="Total number of results")
    next: str | None = Field(None, description="URL for next page")
    previous: str | None = Field(None, description="URL for previous page")
    results: list[MemoryResult] = Field(
        description="List of memory results for current page"
    )


def process_multiple_messages_with_temp_memory(
    messages_batch: list[dict[str, str]],
    query: str,
    inference: bool = False,
    batch_size: int = 5000,
    limit: int = 3,
    threshold: float = 0.5,
    run_id: str | None = None,
) -> list[str]:
    session_id = run_id or f"temp_{int(time.time())}"
    memory: Memory = Memory.from_config(config)

    for i in range(0, len(messages_batch), batch_size):
        batch = messages_batch[i : i + batch_size]
        memory.add(batch, run_id=session_id, infer=inference)

    search_params = {
        "query": query,
        "run_id": session_id,
        "limit": limit,
        "threshold": threshold,
    }

    results = memory.search(**search_params)
    valid_results = SearchResponse(**results)

    return [result.memory for result in valid_results.results]
