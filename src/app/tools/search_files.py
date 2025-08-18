from ripgrepy import Ripgrepy
from pathlib import Path
from pydantic import BaseModel
from src.app.tools.codebase import process_file
from src.app.tools.chunkers import (
    format_chunks_for_memory,
    chunk_text_on_demand,
    chunk_code_on_demand,
)
from src.app.tools.memory import process_multiple_messages_with_temp_memory
from src.app.utils.logger import get_logger

logger = get_logger(__name__)


class SearchMatch(BaseModel):
    """A single search match result."""

    file_path: str
    line_content: str
    line_number: int


def search_files(query: str, paths: list[str] | None = None, literal: bool = False):
    """
    Search current working directory for files matching the given query.

    Args:
        query (str): right-anchored regex pattern to search for.
        paths (list[str] | None): A list of paths to restrict the search to. Must be relative to the current working directory.
            If None, the current working directory is used.
        literal (bool): If True, treat the query as a literal string instead of a regex.

    Returns:
        list[SearchMatch]: A list of search matches.( file_path, line_content, line_number)
    """
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
            pattern = (p / "**" / "*").as_posix()
        else:
            pattern = p.as_posix()

        rg = rg.glob(pattern)

    # Execute and parse results
    try:
        results = rg.run().as_dict
    except Exception as e:
        logger.error(f"ripgrep failed: {e}")
        return []
    matches = []

    for result in results:
        if result.get("type") == "match":
            data = result["data"]
            matches.append(
                SearchMatch(
                    file_path=data["path"]["text"].lstrip("./"),
                    line_content=data["lines"]["text"].rstrip("\n"),
                    line_number=data["line_number"],
                )
            )

    return matches


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
    path = Path(file_path)
    lines = path.read_text().splitlines()

    # Convert to 0-based index
    idx = max(0, start_line - 1)

    start = max(0, idx - before)
    end = min(len(lines), idx + after + 1)

    snippet = lines[start:end]

    return "\n".join(snippet)


# ---------------------------Public Tools--------------------------------


async def similarity_search(
    searchquery: str,
    paths: list[str] | None = None,
    limit: int = 5,
) -> list[str]:
    """
    Search for top-N most similar chunks across all given files.

    Returns
    -------
    list[str]
        Each retrieved chunk includes a banner like:
        [FILE: src/utils/helpers.py | CHUNK: 2]
        <chunk content...>
    """
    if not paths:
        paths = ["."]

    file_desc = await process_file(paths)
    all_chunks: list[str] = []

    for file in file_desc:
        if file.group == "binary":
            continue

        try:
            text = Path(file.file_path).read_text()
        except Exception as e:
            logger.warning(f"Skipping {file.file_path}: {e}")
            continue

        if file.group == "code":
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
        searchquery,
        limit=limit,
    )

    return results
