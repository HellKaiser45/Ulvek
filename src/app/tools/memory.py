from dataclasses import field

from app.tools.search_docs import SearchResult
from pydantic_ai import messages
from src.app.config import config
from mem0 import Memory
import time
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Any, Optional, List, Dict
from src.app.utils.converters import token_count
from src.app.utils.logger import get_logger

logger = get_logger(__name__)


m = Memory.from_config(config)


class MemoryResult(BaseModel):
    memory: str = Field(..., description="The actual memory text content")


custom_prompt = """
Extract technical information including:
- Code snippets and documentation
- API endpoints and configurations
- Error messages and solutions
- Programming concepts

Store this as searchable technical memories.
"""


def process_multiple_messages_with_temp_memory(
    messages_batch: list[dict[str, str]],
    query: str,
    inference: bool = False,
    batch_size: int = 100,
    limit: int = 3,
    threshold: float = 0.5,
    run_id: str | None = None,
) -> list[str]:
    session_id = run_id or f"temp_{int(time.time())}"
    logger.debug(f"receiced query: {query}")
    logger.debug(f"received {len(messages_batch)} chunks")

    try:
        for i in range(0, len(messages_batch), batch_size):
            batch = messages_batch[i : i + batch_size]
            m.add([message for message in batch], infer=inference, run_id=session_id)

        search_params = {
            "query": query,
            "run_id": session_id,
            "limit": limit,
            "threshold": threshold,
        }

        results = m.search(**search_params)
        if not results["results"]:
            logger.warning("No results found")
            return []
        valid_results = [res["memory"] for res in results["results"]]
        logger.debug(f"found {len(valid_results)} valid memories")

        return valid_results

    except Exception as e:
        logger.error(f"Error: {e}")
        raise e

    finally:
        m.delete_all(run_id=session_id)
