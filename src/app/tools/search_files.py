from pathlib import Path
import re
from src.app.tools.codebase import (
    process_file,
    get_non_ignored_files,
    get_magika_instance,
)
from src.app.tools.files_edit import _ensure_in_workspace
from src.app.utils.chunkers import (
    format_chunks_for_memory,
    chunk_text_on_demand,
    chunk_code_on_demand,
)
from src.app.tools.memory import process_multiple_messages_with_temp_memory
from src.app.utils.logger import get_logger
from src.app.utils.converters import token_count
from src.app.config import settings
from src.app.tools.tools_schemas import (
    SearchFilesInput,
    SearchFilesOutput,
    SimilaritySearchOutput,
    SimilaritySearchInput,
    FileChunk,
)
from src.app.agents.schemas import Range
from src.app.tools.file_operations import offset_to_position

logger = get_logger(__name__)


async def search_files(input_data: SearchFilesInput) -> list[SearchFilesOutput]:
    """Search for text patterns within file contents (not file names).

    Use this tool when you need to find specific code, text, or patterns within files."""
    dir = input_data.folder_path or Path(".")
    logger.debug(f"Searching for {input_data.pattern} files in {dir}")

    try:
        _ensure_in_workspace(dir)
        regex = (
            re.compile(input_data.pattern, re.IGNORECASE)
            if input_data.case_sensitive
            else re.compile(input_data.pattern)
        )
    except Exception as e:
        error_msg = f"Invalid regex pattern: {e}"
        logger.error(error_msg)
        return [
            SearchFilesOutput(
                status="error",
                error_message=error_msg,
                searched_pattern=input_data.pattern,
                file_path=dir,
                ranges=[],
            )
        ]

    output = []

    for file in dir.rglob("*"):
        if file.is_file() and file in await get_non_ignored_files():
            content = file.read_text()
            matches = regex.finditer(content)

            if matches:
                ranges = []
                for match in matches:
                    pstart = offset_to_position(content, match.start())
                    pend = offset_to_position(content, match.end())

                    ranges.append(Range(start=pstart, end=pend))
                output.append(
                    SearchFilesOutput(
                        status="ok",
                        searched_pattern=input_data.pattern,
                        file_path=file,
                        ranges=ranges,
                    )
                )
            else:
                output.append(
                    SearchFilesOutput(
                        status="no_results",
                        searched_pattern=input_data.pattern,
                        file_path=file,
                        ranges=[],
                    )
                )
    logger.debug(f"Found {len(output)} matches")
    logger.debug(f"total tokens: {token_count(str(output))}")

    return output


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
    input_data: SimilaritySearchInput,
) -> list[FileChunk]:
    """
    Perform semantic similarity search across files to find relevant content chunks.

    Uses embeddings and vector similarity to find the most relevant chunks of text
    that answer the given question.
    """

    if not input_data.paths:
        input_data.paths = [Path(file) for file in await get_non_ignored_files()]

    logger.debug(
        f"Searching for similarity in {input_data.paths} for question: {input_data.question}"
    )

    magika = await get_magika_instance()
    all_chunks = []

    for path in input_data.paths:
        if not path.resolve().is_relative_to(Path.cwd().resolve()):
            logger.error(
                f"Path {path} is not relative to the current working directory."
            )
        if not path.resolve().is_file():
            logger.error(f"Path {path} is not a file.")

        else:
            content = path.read_text()

            file = magika.identify_path(path)

            if file.output.label in supported_languages:
                chunks = chunk_code_on_demand(content, language=file.output.label)
                logger.debug(
                    f"Processing file {path} as a code file with {file.output.label} language"
                )
            else:
                chunks = chunk_text_on_demand(content)
                logger.debug(f"Processing file {path} as a text file")

            all_chunks.extend(
                FileChunk(
                    file_path=path,
                    text=chunk.text,
                    range=Range(start=chunk.range.start, end=chunk.range.end),
                    token_count=chunk.token_count,
                )
                for chunk in chunks
            )
    text_chunks = [chunk.model_dump_json() for chunk in all_chunks]
    logger.debug(f"Found {len(text_chunks)} chunks")

    formatted_chunks = format_chunks_for_memory(text_chunks)

    result = process_multiple_messages_with_temp_memory(
        formatted_chunks,
        input_data.question,
        limit=input_data.limit,
        threshold=input_data.threshold,
    )
    result_string = result
    logger.debug(f"Found {len(result_string)} similar chunks")
    logger.debug(f"total tokens: {token_count(str(result_string))}")

    return [FileChunk.model_validate_json(s) for s in result_string]


if __name__ == "__main__":
    import asyncio

    asyncio.run(
        similarity_search(
            SimilaritySearchInput(
                question="Agent definition system_prompt", threshold=0.5
            )
        )
    )
