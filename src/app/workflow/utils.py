import asyncio
from src.app.tools.codebase import process_file, get_non_ignored_files
from langchain_core.runnables.config import RunnableConfig
from typing import cast


async def build_static() -> str:
    files = await get_non_ignored_files()
    desc = await process_file(files)
    return "\n".join(f"- {f.file_path}: {f.description}" for f in desc)


def get_event_queue_from_config(config: RunnableConfig) -> asyncio.Queue:
    """
    Safely retrieves the asyncio.Queue from the RunnableConfig.

    Args:
        config: The RunnableConfig passed to the LangGraph node.

    Returns:
        The event queue instance.

    Raises:
        ValueError: If the event queue is not found or is of the wrong type.
    """
    metadata = config.get("metadata", {})
    event_queue = metadata.get("event_queue")

    if not isinstance(event_queue, asyncio.Queue):
        raise ValueError(
            "An 'event_queue' of type asyncio.Queue was not found in the "
            "RunnableConfig's metadata. Please ensure it is passed correctly."
        )

    return cast(asyncio.Queue, event_queue)
