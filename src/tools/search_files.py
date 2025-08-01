from ripgrepy import Ripgrepy
from pathlib import Path
from pydantic import BaseModel, field_validator, Field, TypeAdapter
from typing import Any
from src.tools.codebase import process_file, FileAnalysis
from src.tools.chunkers import (
    format_chunks_for_memory,
    chunk_text_on_demand,
    chunk_code_on_demand,
)
from src.tools.memory import process_multiple_messages_with_temp_memory

import time


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


async def search_files(
    ripgrep_query: str, file_or_files: str | list[str]
) -> list[SearchContent]:
    """Async file search with proper I/O handling"""

    matches = _get_ripgrep_matches(ripgrep_query, file_or_files)
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
            print(f"Processing code file at {file.file_path}")
            chunks = format_chunks_for_memory(
                chunk_code_on_demand(text, language=file.file_type)
            )
        else:
            print(f"Processing text file at {file.file_path}")
            chunks = format_chunks_for_memory(chunk_text_on_demand(text))

        # Process memory (RAG results)
        memory = process_multiple_messages_with_temp_memory(chunks, ripgrep_query)

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


def _get_ripgrep_matches(query: str, paths: list[str] | str) -> list[SearchMatch]:
    root = Path.cwd().resolve()
    print("the dir is ", root)
    rg = Ripgrepy(query, str(root)).line_number().fixed_strings().json()
    if isinstance(paths, str):
        paths = [paths]
    for f in paths:
        abs_path = Path(f).expanduser().resolve()
        rel = abs_path.relative_to(root)
        rg = rg.glob(str(rel))

    rg = rg.glob("!main.py")

    out = rg.run().as_dict

    if len(out) == 0:
        return []

    adapter = TypeAdapter(list[SearchMatch])

    return adapter.validate_python(out)


def enclosing_block(
    file_path: str,
    line_number: int,
    max_lines: int = 100,
    max_chars: int = 5000,
) -> str:
    """
    Return ±max_lines around the hit line, trimmed to the nearest blank line.
    Handles indented blocks in any language reasonably well.
    """
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
    print("".join(lines[start:end]))

    return "".join(lines[start:end])
