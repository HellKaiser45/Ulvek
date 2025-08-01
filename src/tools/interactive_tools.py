"""
interactive_tools.py – synchronous utilities for interactive CLI prompts.
"""

from pydantic import BaseModel, Field
from src.tools.chunkers import chunk_docs_on_demand, format_chunks_for_memory
from src.tools.memory import process_multiple_messages_with_temp_memory
from src.tools.search_docs import AsyncContext7Client


# ------------------------------------------------------------------
# Pydantic model that groups every “secondary” parameter
# ------------------------------------------------------------------
class SearchConfig(BaseModel):
    limit: int = Field(
        3,
        ge=1,
        description="Maximum number of relevant snippets to return from the memory layer.",
    )
    library_to_search: str = Field(
        ...,
        description="Library or framework name to search on Context7 (e.g. 'react', 'fastapi').",
    )
    search_in_library: str = Field(
        ...,
        description="Free-text query used to retrieve the most relevant snippets from the fetched documentation.",
    )
    threshold: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="Relevance threshold for Mem0 search; higher values return fewer but more relevant snippets.",
    )
    delimiters: tuple[str, ...] = Field(
        ("----------------------------------------",),
        description="Strings that delimit logical sections when chunking the documentation text.",
    )


async def gather_docs_context(params: SearchConfig) -> list[str]:
    """
    Search Context7 for a library and immediately fetch its documentation.

    Parameters
    ----------
    params : SearchConfig
        Configuration object for the search.

    Returns
    -------
    list[str]
        List of documentation strings for the best-matched library.
    """
    async with AsyncContext7Client() as client:
        docs, tokens, title = await client.search_and_fetch(
            query=params.library_to_search
        )

    if docs:
        formatted_chunks = format_chunks_for_memory(chunk_docs_on_demand(docs))
        return process_multiple_messages_with_temp_memory(
            messages_batch=formatted_chunks, query=params.search_in_library
        )

    return []


def prompt_user(prompt: str | list[str]) -> str:
    """
    Prompt the user interactively and return the raw string response.

    Parameters
    ----------
    prompt : str | list[str]
        A single question or a list of questions to display to the user.
        If a list is provided, each element is printed on its own line.

    Returns
    -------
    str
        The exact text entered by the user (empty string if the user just presses Enter).
    """
    if isinstance(prompt, list):
        for line in prompt:
            print(line)
        question = "> "
    else:
        question = f"{prompt} "

    try:
        return input(question).rstrip("\n")
    except (KeyboardInterrupt, EOFError):
        # Gracefully return empty string on Ctrl-C / Ctrl-D
        print()
        return ""
