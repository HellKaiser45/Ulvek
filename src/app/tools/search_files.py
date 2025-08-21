from ripgrepy import Ripgrepy
from pathlib import Path
from pydantic import BaseModel, Field, FilePath, DirectoryPath
import os
import json
from typing import Sequence, Literal
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


class SearchFilesInput(BaseModel):
    """Schema for search_files tool input."""

    query: str = Field(..., description="Search query string")
    paths: list[FilePath | DirectoryPath] | None = Field(
        default=None,
        description="Relative file/directory paths to search within. Defaults to project root.",
    )
    literal: bool = Field(
        False,
        description="If true, treats the query as a literal string instead of a regex",
    )


class SearchMatch(BaseModel):
    """A single search match result."""

    file_path: str
    line_content: str
    line_number: int


class SearchResponse(BaseModel):
    """Structured response for search_files tool."""

    status: Literal["ok", "no_results", "error"]
    matches: list[SearchMatch] = []
    error_message: str | None = None


async def search_files(input_data: SearchFilesInput) -> SearchResponse:
    """Search for files matching the given query with structured output."""

    query = input_data.query
    paths = input_data.paths or ["."]
    literal = input_data.literal

    working_dir = Path.cwd()
    logger.debug(f"Working directory: {working_dir}")
    logger.info(f"Searching for '{query}' in paths: {paths}")

    rg = Ripgrepy(query, str(working_dir)).line_number().json().ignore_case()
    if literal:
        rg = rg.fixed_strings()

    for path_str in paths:
        path = Path(path_str)
        if path.is_absolute():
            msg = f"Absolute paths not supported: {path}"
            logger.error(msg)
            return SearchResponse(status="error", error_message=msg)

        rg = (
            rg.glob(str(path))
            if not (working_dir / path).is_dir()
            else rg.glob(f"{path}/**/*")
        )

    try:
        results = rg.run().as_dict
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON from ripgrep: {e}"
        logger.error(msg)
        return SearchResponse(status="error", error_message="Invalid search query")
    except Exception as e:
        msg = f"Search failed: {e}"
        logger.error(msg)
        return SearchResponse(status="error", error_message=str(e))

    matches: list[SearchMatch] = []
    for result in results:
        if result.get("type") == "match":
            data = result["data"]
            raw_path = Path(data["path"]["text"]).relative_to(os.getcwd()).as_posix()
            matches.append(
                SearchMatch(
                    file_path=raw_path,
                    line_content=data["lines"]["text"].rstrip("\n"),
                    line_number=data["line_number"],
                )
            )

    if matches:
        logger.info(f"Found {len(matches)} matches")
        return SearchResponse(status="ok", matches=matches)
    else:
        logger.info("No results found")
        return SearchResponse(status="no_results")


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
    try:
        _ensure_in_workspace(path)
    except ValueError as e:
        logger.error(f"Error in extract_snippet: {e}")
        return str(e)

    if not path.exists():
        logger.error(f"File not found: {file_path}")
        return f"File not found: {file_path}"

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
    for result in results:
        logger.info(f"Similarity search result: {result[:100]}...")
    logger.info(
        f"Similarity search finished with {len(results)} results and a total of {total_tokens} tokens"
    )

    if total_tokens > settings.MAX_CONTEXT_TOKENS / 5:
        return f"the results are too long try again by setting the limit to a lower value than {limit}"

    return results


similarity_search_description = """⚠️ EXPENSIVE TOOL - Use only when absolutely necessary ⚠️
    
    Performs semantic similarity search across code chunks using AI embeddings.
    This is a HIGH-COST operation that should be your LAST RESORT after trying
    lightweight alternatives like ripgrep or file structure analysis.
    
    🔴 WHEN TO USE:
    - You need to find conceptually similar code (not exact patterns)
    - You're looking for implementations of abstract concepts
    - You need to understand how a specific algorithm/pattern is implemented
    - Ripgrep and file structure search have failed to find what you need
    
    🚫 WHEN NOT TO USE:
    - Looking for exact strings, function names, or imports → use ripgrep
    - Understanding project structure or file relationships → use file structure tools
    - Finding error messages or logs → use ripgrep  
    - Exploring a new codebase → start with file structure + ripgrep
    - You already have sufficient context to answer the user's question
    
    Args:
        question (str): A focused, specific semantic search query. 
            ✅ GOOD: "authentication middleware that handles JWT tokens"
            ✅ GOOD: "error handling patterns for database connections" 
            ✅ GOOD: "how user permissions are validated"
            ❌ BAD: "how does this work" (too vague)
            ❌ BAD: "authentication" (too broad, use ripgrep instead)
            ❌ BAD: "show me the code" (not semantic)
            
        paths (list[str] | None): Restrict search to specific directories/files.
            ✅ GOOD: ["src/auth", "src/middleware"] (focused search)
            ✅ GOOD: ["app.py", "main.py"] (specific files)  
            ✅ GOOD: ["src"] (one main directory)
            ❌ BAD: ["."] or None (searches entire project - very expensive)
            ❌ BAD: ["src", "tests", "docs", "config"] (too broad)
            
            💡 TIP: Use file structure or ripgrep results to identify relevant paths first
            
        limit (int): Maximum chunks to return. Default 5.
            ✅ GOOD: 3-5 for focused searches
            ✅ GOOD: 1-2 if you just need one example
            ❌ BAD: 10+ (expensive and usually unnecessary)
            
            💡 TIP: Start with limit=3, increase only if results are insufficient
    
    Returns:
        list[str]: Relevant code chunks with file/chunk metadata banners:
            [FILE: src/auth/middleware.py | CHUNK: 2]
            <actual code content>
            
        str: Error message if results are too large (exceeds token limits)
            → Retry with smaller limit or more focused paths
    
    ⚡ PERFORMANCE NOTES:
    - Cost scales with: (number of files) × (file sizes) × (semantic complexity)
    - Searching entire project (paths=["."] or None) can be 10-50x more expensive
    - Always prefer targeted searches over broad exploration
    
    🎯 USAGE STRATEGY:
    1. First try: ripgrep for exact patterns, imports, function names
    2. Then try: file structure analysis to understand project layout  
    3. Finally try: similarity_search with focused question + targeted paths (only if needed)
    
    💡 EXPERT TIP: 
    If you're tempted to call this multiple times, you're probably using it wrong.
    One well-crafted call with specific paths should be sufficient.
    """
