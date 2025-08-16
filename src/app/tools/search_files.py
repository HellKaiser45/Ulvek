from ripgrepy import Ripgrepy
from pathlib import Path
from pydantic import BaseModel, field_validator, Field, TypeAdapter
from typing import Any, Optional
from src.app.tools.codebase import process_file, FileAnalysis
from src.app.tools.chunkers import (
    format_chunks_for_memory,
    chunk_text_on_demand,
    chunk_code_on_demand,
)
from src.app.tools.memory import process_multiple_messages_with_temp_memory
from src.app.utils.logger import get_logger

logger = get_logger(__name__)


class MatchText(BaseModel):
    text: str


class SubMatch(BaseModel):
    match: MatchText
    start: int
    end: int


class PathData(BaseModel):
    text: str


class LinesData(BaseModel):
    text: str


class MatchData(BaseModel):
    path: PathData
    lines: LinesData
    line_number: int
    absolute_offset: int
    submatches: list[SubMatch] = Field(default_factory=list)


class SearchMatch(BaseModel):
    type: str = Field(default="match")
    data: MatchData


class SearchResult(FileAnalysis):
    line_number: int
    line_content: str

    @field_validator("line_number", mode="before")
    def validate_line_number(cls, v: Any) -> int:
        return int(v) if isinstance(v, str) else v


class SearchContent(SearchResult):
    content_rag_result: list[str]
    content_extract: str


class RipgrepSearchRequest(BaseModel):
    query: str = Field(
        ...,
        description="Search term.  Can be a plain string or a regular expression "
        "unless `literal=True` is set.",
    )

    paths: list[str] = Field(
        ...,
        description="File(s) or directory/ies to restrict the search to, "
        "relative to the current working directory.",
    )

    literal: bool = Field(
        False,
        description="If True, treat `query` as a literal string instead of a regex.",
    )

    case_insensitive: bool = Field(
        False,
        description="Perform case-insensitive matching (-i flag).",
    )

    context: Optional[int] = Field(
        None,
        ge=0,
        description="Number of lines of context to show both before "
        "and after each match (-C flag).",
    )

    max_count: Optional[int] = Field(
        None,
        gt=0,
        description="Stop after finding this many matching lines in total.",
    )


class Search_file_request(BaseModel):
    ask_docs: str = Field(
        ...,
        description="The prompt to ask the LLM to search for topics/functions/classes/etc in the codebase.",
    )
    ripgrep_request: RipgrepSearchRequest = Field(
        ...,
        description="The request to pass to ripgrep.",
    )


def _get_ripgrep_matches(req: RipgrepSearchRequest) -> list[SearchMatch]:
    root = Path.cwd().resolve()
    rg = Ripgrepy(req.query, str(root)).line_number().json()

    if req.literal:
        rg = rg.fixed_strings()
    if req.case_insensitive:
        rg = rg.ignore_case()
    if req.context:
        rg = rg.context(req.context)
    if req.max_count:
        rg = rg.max_count(req.max_count)

    for p in req.paths:
        abs_path = Path(p).expanduser().resolve()
        rel = abs_path.relative_to(root)
        rg = rg.glob(str(rel))

    rg = rg.glob("!main.py")

    raw = rg.run().as_dict
    if not raw:  # empty list or falsy
        return []

    try:
        adapter = TypeAdapter(list[SearchMatch])
        return adapter.validate_python(raw)
    except Exception as e:
        # log once, return empty instead of exploding the agent
        logger.warning(f"ripgrepy JSON decode failed: {e}")
        return []


def enclosing_block(
    file_path: str,
    line_number: int,
    max_lines: int = 100,
    max_chars: int = 5000,
) -> str:
    path = Path(file_path)
    lines = path.read_text().splitlines(keepends=True)

    start = max(0, line_number)
    end = min(len(lines), line_number + 1)

    line_count = end - start
    chars_count = len("".join(lines[start:end]))

    # Expand upward until we hit a blank line or limits
    while (
        start > 0
        and lines[start - 1].strip() != ""
        and line_count < max_lines
        and chars_count + len(lines[start - 1]) < max_chars
    ):
        start -= 1
        line_count += 1
        chars_count += len(lines[start])

    # Expand downward until we hit a blank line or limits
    while (
        end < len(lines)
        and lines[end].strip() != ""
        and line_count < max_lines
        and chars_count + len(lines[end]) < max_chars
    ):
        chars_count += len(lines[end])
        end += 1
        line_count += 1

    return "".join(lines[start:end])


# ---------------------------Public Tools--------------------------------
async def search_files(searchquery: Search_file_request) -> list[SearchContent]:
    """
    End-to-end “smart search” over the current workspace.

    What the function does
    ----------------------
    1. Runs **ripgrep** with the options supplied in
       `searchquery.ripgrep_request`, returning every matching line.
    2. De-duplicates the files that contain at least one hit and
       asynchronously analyses them (`process_file`) to obtain
       language, file type, etc.
    3. Reads the full content of each file and chunks it:
       - code → language-aware chunks
       - plain text → simple text chunks
    4. Sends the chunks to an LLM together with the prompt
       `searchquery.ask_docs`, performing a **RAG retrieval** that
       returns the most relevant snippets.
    5. Extracts the **enclosing syntactic block** (class / function /
       markdown section, etc.) that contains the hit line.
    6. Returns a list of `SearchContent` objects, one per **match**,
       that combine:

       - the original ripgrep hit (file path, line number, line text)
       - file-level metadata (language, file type, …)
       - the RAG-selected snippets (`content_rag_result`)
       - the enclosing block (`content_extract`)


    Returns
    -------
    list[SearchContent]
        One entry per **matching line** returned by ripgrep, enriched
        with RAG results and enclosing context.


    """
    matches = _get_ripgrep_matches(searchquery.ripgrep_request)
    results_paths = {match.data.path.text for match in matches}
    files_analysis = await process_file(list(results_paths))

    validated_files = [
        SearchResult(
            **fa.model_dump(),
            line_number=int(match.data.line_number),
            line_content=match.data.lines.text,
        )
        for match, fa in zip(matches, files_analysis)
    ]
    search_results = []
    for file in validated_files:
        text = Path(file.file_path).read_text()

        if file.group == "code":
            chunks = format_chunks_for_memory(
                chunk_code_on_demand(text, language=file.file_type)
            )
        else:
            chunks = format_chunks_for_memory(chunk_text_on_demand(text))

        # Process memory (RAG results)
        memory = process_multiple_messages_with_temp_memory(
            chunks, searchquery.ask_docs
        )

        # Extract surrounding content
        content = enclosing_block(file.file_path, file.line_number)

        # Create SearchContent object
        search_results.append(
            SearchContent(
                **file.model_dump(),  # Inherits all SearchResult fields
                content_rag_result=memory,  # List[str] from RAG
                content_extract=content,  # str from enclosing_block
            )
        )

    return search_results
