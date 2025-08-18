from ripgrepy import Ripgrepy
from pathlib import Path
from pydantic import BaseModel
import os
import json
from src.app.tools.codebase import process_file, get_non_ignored_files
from src.app.tools.files_edit import _ensure_in_workspace
from src.app.tools.chunkers import (
    format_chunks_for_memory,
    chunk_text_on_demand,
    chunk_code_on_demand,
)
from src.app.tools.memory import process_multiple_messages_with_temp_memory
from src.app.utils.logger import get_logger
from src.app.utils.converters import token_count
from src.app.config import settings

logger = get_logger(__name__)


class SearchMatch(BaseModel):
    """A single search match result."""

    file_path: str
    line_content: str
    line_number: int


async def search_files(
    query: str, paths: list[str] | None = None, literal: bool = False
):
    """
    Search current working directory for files matching the given query the query will be searched in all files in the list of paths paths.
    Or in the current working directory if paths is None.
    But the query is not a file or file path but a regex pattern.
    Args:
        query (str): right-anchored regex pattern to search for.
        paths (list[str] | None): A list of paths to restrict the search to. Must be relative to the current working directory.
            If None, the current working directory is used.
        literal (bool): If True, treat the query as a literal string instead of a regex.
    Returns:
        list[SearchMatch]: A list of search matches.( file_path, line_content, line_number)
    """
    logger.info(f"rg search for {query} in {paths}")
    if paths is None or len(paths) == 0:
        paths = ["."]
    working_dir = Path.cwd()

    rg = Ripgrepy(query, str(working_dir)).line_number().json().ignore_case()
    if literal:
        rg = rg.fixed_strings()
    for path in paths:
        p = Path(path)
        # 🔒 Reject absolute paths
        if p.is_absolute():
            raise ValueError(f"Absolute paths not supported: {path}")
        # Now safe to resolve relative to CWD
        full_path = working_dir / p  # Always resolve from CWD
        if full_path.is_dir():
            rg = rg.glob(f"{p}/**/*")
        else:
            rg = rg.glob(str(p))
    try:
        results = rg.run().as_dict
    except json.JSONDecodeError as e:
        logger.error(f"ripgrep returned invalid JSON: {e}")
        return "invalid search query (maybe you included a newline or malformed regex)"
    except Exception as e:
        logger.error(f"ripgrep failed: {e}")
        return "ripgrep search failed, please refine your query"
    matches = []
    non_ignored_files = await get_non_ignored_files()
    for result in results:
        if result.get("type") == "match":
            data = result["data"]
            raw_path = Path(data["path"]["text"]).relative_to(os.getcwd()).as_posix()
            if raw_path in non_ignored_files:
                matches.append(
                    SearchMatch(
                        file_path=str(raw_path),
                        line_content=data["lines"]["text"].rstrip("\n"),
                        line_number=data["line_number"],
                    )
                )
    token_count_total = token_count(str(matches))
    if token_count_total > settings.MAX_CONTEXT_TOKENS / 5:
        return "the results are too long try again by selecting more carefully your search query or file paths"
    return matches if len(matches) > 0 else "no results found"


def extract_snippet(
    file_path: str, start_line: int, before: int = 0, after: int = 0
) -> str:
    """
    Extract a part of a file.
    Parameters
    ----------
    file_path : str
        Path to the file.
    start_line : int
        1-based line number to center the snippet on.
    before : int
        Number of lines before `start_line` to include.
    after : int
        Number of lines after `start_line` to include.
    Returns
    -------
    str
        Raw snippet including the requested context.
    """
    logger.info(
        f"triying to extract snippet from {file_path} at {start_line} with {before} before and {after} after"
    )
    path = Path(file_path)
    _ensure_in_workspace(path)  # Security check

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        lines = path.read_text().splitlines()
    except Exception as e:
        raise IOError(f"Failed to read file {file_path}: {e}")

    # Convert to 0-based index
    idx = max(0, start_line - 1)
    start = max(0, idx - before)
    end = min(len(lines), idx + after + 1)
    snippet = lines[start:end]

    total_tokens = token_count("\n".join(snippet))

    if total_tokens > settings.MAX_CONTEXT_TOKENS / 5:
        return f"the results are too long try again by narrowing the before and after lines lower values than {before} and {after}"

    return "\n".join(snippet)


supported_languages = {
    "python",
    "typescript",
    "javascript",
    "rust",
    "go",
    "java",
    "c",
    "c++",
    "c#",
    "html",
    "css",
    "markdown",
}


async def similarity_search(
    question: str,
    paths: list[str] | None = None,
    limit: int = 5,
) -> list[str] | str:
    """similarity search for top-N most similar chunks across all given files. Provide a natural language question to search for.
       Args:
        question (str): similarity search query. e.g."what are the current agent definitions"
        paths (list[str] | None): A list of paths to restrict the search to.
        If None, the current working directory is used.
        limit (int): Maximum number of results to return.

    Returns
    -------
    list[str]
        Each retrieved chunk includes a banner like:
        [FILE: src/utils/helpers.py | CHUNK: 2]
        <chunk content...>
    """
    logger.info(f"similarity search started for {paths} with {question}")
    if not paths:
        paths = ["."]

    # Validate all paths are in workspace
    for path in paths:
        p = Path(path)
        if p.is_absolute():
            raise ValueError(f"Absolute paths not supported: {path}")
        full_path = Path.cwd() / p
        _ensure_in_workspace(full_path)

    all_non_ignored = await get_non_ignored_files()

    filtered_paths = []
    for path in paths:
        p = Path(path)
        if p == Path("."):
            # If searching root, use all non-ignored files
            filtered_paths.extend(all_non_ignored)
        else:
            # Filter for files within this path
            for file_path in all_non_ignored:
                file_path_obj = Path(file_path)
                try:
                    file_path_obj.relative_to(p)
                    filtered_paths.append(file_path)
                except ValueError:
                    continue

    if not filtered_paths:
        logger.info("No non-ignored files found in specified paths")
        return []

    # Process only the filtered, non-ignored files
    file_desc = await process_file(filtered_paths)
    all_chunks: list[str] = []

    for file in file_desc:
        if file.group == "binary":
            continue
        try:
            text = Path(file.file_path).read_text()
        except Exception as e:
            logger.warning(f"Skipping {file.file_path}: {e}")
            continue

        if file.group == "code" and file.file_type.lower() in supported_languages:
            chunks = chunk_code_on_demand(text, language=file.file_type)
        else:
            chunks = chunk_text_on_demand(text)

        # prefix each chunk with file metadata banner
        for i, chunk in enumerate(chunks, start=1):
            banner = f"[FILE: {file.file_path} | CHUNK: {i}]\n"
            all_chunks.append(banner + chunk)

    if not all_chunks:
        return []

    # Run one global similarity search across all annotated chunks
    formatted_chunks = format_chunks_for_memory(all_chunks)
    results = process_multiple_messages_with_temp_memory(
        formatted_chunks,
        question,
        limit=limit,
    )

    total_tokens = token_count(str(results))

    if total_tokens > settings.MAX_CONTEXT_TOKENS / 5:
        return f"the results are too long try again by setting the limit to a lower value than {limit}"

    return results
