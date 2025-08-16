from pydantic import BaseModel, Field
from src.app.tools.chunkers import chunk_docs_on_demand, format_chunks_for_memory
from src.app.tools.memory import process_multiple_messages_with_temp_memory
from src.app.tools.search_docs import AsyncContext7Client


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


async def prompt_user(
    prompt: str | list[str],
) -> str:
    """
    Prompt the user via AG-UI and return the raw string response.
    The conversation id is taken from `ctx.deps.run_id`.
    """
    return ""
