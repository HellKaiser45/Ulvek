from pydantic import BaseModel, Field, FilePath, DirectoryPath
from typing import Literal
from pathlib import Path
from src.app.agents.schemas import Position, Range
from src.app.utils.chunks_schemas import ChunkOutputSchema


class BaseOutputSchema(BaseModel):
    """Base schema for all tool output schemas."""

    status: Literal["ok", "error", "no_results"]
    error_message: str | None = None


class SearchFilesInput(BaseModel):
    """Schema for search_files tool input."""

    pattern: str = Field(
        ...,
        description="Text or regex pattern to search FOR within file contents (not file names). "
        "Example: 'def my_function' or 'import.*json'",
    )
    folder_path: Path | DirectoryPath | None = Field(
        default=None,
        description="Relative file/directory paths to search within. Defaults to project root.",
    )

    case_sensitive: bool = Field(
        default=False,
        description="if true the query is case sensitive",
    )


class SearchFilesOutput(BaseOutputSchema):
    """Schema for search_files tool output."""

    searched_pattern: str = Field(..., description="The search query that was executed")
    file_path: Path = Field(..., description="The file path that was searched")
    ranges: list[Range] = Field(..., description="List of match positions in the file")


class SimilarityMatch(BaseModel):
    """A single similarity search result."""

    file_path: str = Field(..., description="Path to the file containing the match")
    chunk_number: int = Field(..., description="Chunk number within the file")
    content: str = Field(..., description="Content of the matching chunk")
    relevance_score: float | None = Field(
        default=None, description="Relevance score if available"
    )


class FileChunk(ChunkOutputSchema):
    """A single chunk from a file."""

    file_path: Path | FilePath = Field(
        ..., description="Path to the file containing the chunk"
    )


class SimilaritySearchInput(BaseModel):
    """Schema for similarity_search tool input."""

    question: str = Field(
        ..., description="Natural-language question or code fragment to match"
    )
    paths: list[Path | FilePath] | None = Field(
        default=None,
        description="Relative paths to restrict search to. Defaults to all files in the project.(heavy operation)",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of results to return",
    )
    threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum score threshold for results",
    )


class SimilaritySearchOutput(BaseOutputSchema):
    """Schema for similarity_search tool output."""

    question: str = Field(..., description="The search question that was executed")
    paths_searched: list[str] = Field(..., description="Paths that were searched")
    matches: list[SimilarityMatch] = Field(
        default=[], description="List of similarity matches found"
    )
    total_matches: int = Field(..., description="Total number of matches found")
    total_tokens: int = Field(..., description="Total tokens in all results")
    truncated: bool = Field(
        default=False, description="Whether results were truncated due to token limits"
    )


# --------------------------------Line Content -------------------------------------


class LineContentOutput(BaseOutputSchema):
    """Schema for line_content tool input."""

    file_path: Path = Field(
        ...,
        description="Path to the file to read. Can be relative to the current working directory.",
    )
    line_number: int = Field(
        ...,
        description="Line number read. 1-indexed.",
    )
    content: str = Field(
        ...,
        description="Content of the line.",
    )


class RangeOutput(BaseOutputSchema):
    """Schema for range_content tool input."""

    file_path: Path = Field(
        ...,
        description="Path to the file to read. Can be relative to the current working directory.",
    )
    start_line: int = Field(
        ...,
        description="Start line of the range. 1-indexed.",
    )
    end_line: int = Field(
        ...,
        description="End line of the range. 1-indexed.",
    )
    content: str = Field(
        ...,
        description="Content of the range.",
    )


class ReadFileContentOutput(BaseOutputSchema):
    """Schema for read_file_content tool input."""

    file_path: Path = Field(
        ...,
        description="Path to the file to read. ",
    )
    content: str = Field(
        ...,
        description="Content of the file, as a string. This could be truncated if the file is considered too large.",
    )


class PostitiontoOffsetOutput(BaseOutputSchema):
    """Schema for position_to_offset tool input."""

    character: int = Field(
        ...,
        description="Character offset (int) representing the absolute position in the string content.",
    )
    position: Position = Field(
        ...,
        description="Position in the file. 1-indexed.",
    )


class FindTextInFileOutput(BaseOutputSchema):
    """Schema for find_text_in_file tool input."""

    positions: list[Position] = Field(..., description="List of positions in the file.")
