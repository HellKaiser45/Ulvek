from pathlib import Path
import asyncio
from collections import defaultdict
from src.app.tools.codebase import (
    get_non_ignored_files,
    get_magika_instance,
)
from src.app.utils.chunkers import (
    format_chunks_for_memory,
    chunk_text_on_demand,
    chunk_code_on_demand,
    prefilter_bm25,
)
from src.app.tools.memory import process_multiple_messages_with_temp_memory
from src.app.utils.logger import get_logger
from src.app.utils.converters import token_count
from src.app.tools.tools_schemas import (
    SearchFilesInput,
    SearchFilesOutput,
    SimilaritySearchInput,
    FileChunk,
)
from src.app.agents.schemas import Range
import json
from src.app.tools.file_operations import offset_to_position

logger = get_logger(__name__)


async def search_files(input_data: SearchFilesInput) -> list[SearchFilesOutput]:
    f"""{search_files.__name__} | Search files for a given pattern in the current directory.
    
    Retreive a list of files that match the given pattern. This is a wrapper around the `rg` command-line tool.
    You can use the `pattern` field to specify a regular expression or a simple string to search for.
    The goal is to have a tool that enriches the knowledge of the codebase. And allow a better understanding of the codebase.

    Args:
        input_data (SearchFilesInput): {SearchFilesInput.model_json_schema()}

    """
    dir = input_data.folder_path or Path(".")
    logger.debug(f"Searching for {input_data.pattern} pattern in {dir}")

    cmd = [
        "rg",
        "--json",
        "-i" if not input_data.case_sensitive else None,
        input_data.pattern,
        str(dir),
    ]
    cmd = [c for c in cmd if c is not None]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode not in (0, 1):
        logger.error("ripgrep failed: %s", stderr.decode())
        return [
            SearchFilesOutput(
                status="error",
                error_message=stderr.decode(),
                searched_pattern=input_data.pattern,
                file_path=dir,
                ranges=[],
            )
        ]

    files: dict[Path, list[Range]] = defaultdict(list)

    for line in stdout.splitlines():
        js = json.loads(line)
        if js.get("type") != "match":
            continue

        path = Path(js["data"]["path"]["text"])
        content = path.read_text()

        for sub in js["data"]["submatches"]:
            start_pos = offset_to_position(content, sub["start"])
            end_pos = offset_to_position(content, sub["end"])
            files[path].append(Range(start=start_pos, end=end_pos))

    output = [
        SearchFilesOutput(
            status="ok",
            searched_pattern=input_data.pattern,
            file_path=p,
            ranges=ranges,
        )
        for p, ranges in files.items()
    ]

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
    f"""{search_files.__name__} | Perform semantic similarity search across files to find relevant content chunks.

    
    Uses embeddings and vector similarity to find the most relevant chunks of text
    that answer the given question.

    Args:
        input_data (SimilaritySearchInput): {SimilaritySearchInput.model_json_schema()}
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
            logger.warning(
                f"Path {path} is not relative to the current working directory."
            )

        if not path.resolve().is_file():
            logger.warning(f"Path {path} is not a file.")

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

    filtered_chunks = prefilter_bm25(text_chunks, input_data.question)

    formatted_chunks = format_chunks_for_memory(filtered_chunks)

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
    asyncio.run(search_files(SearchFilesInput(pattern="class.*Agent")))

    # asyncio.run(
    #     similarity_search(
    #         SimilaritySearchInput(
    #             question="Agent definition system_prompt", threshold=0.5
    #         )
    #     )
    # )
