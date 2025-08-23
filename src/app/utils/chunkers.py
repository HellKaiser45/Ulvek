from chonkie import (
    CodeChunker,
    RecursiveLevel,
    SemanticChunker,
    RecursiveRules,
    RecursiveChunker,
)
from src.app.config import settings, tokenizer
from tokenizers import Tokenizer
from itertools import chain
from operator import attrgetter
from functools import lru_cache
from src.app.utils.chunks_schemas import ChunkOutputSchema
from src.app.tools.file_operations import offset_to_position
from src.app.agents.schemas import Range


@lru_cache(maxsize=2)
def get_code_chunker(
    tokenizer: Tokenizer = tokenizer,
    language: str = "auto",
    chunk_size=512,
) -> CodeChunker:
    return CodeChunker(
        language=language,
        tokenizer_or_token_counter=tokenizer,
        chunk_size=chunk_size,
        include_nodes=False,
    )


def chunk_code_on_demand(
    code_to_chunk: str,
    tokenizer: Tokenizer = tokenizer,
    language: str = "auto",
    chunk_size=512,
) -> list[ChunkOutputSchema]:
    chunks = get_code_chunker(tokenizer, language, chunk_size).chunk(code_to_chunk)

    chunks_output = []

    for chunk in chunks:
        start_pos = offset_to_position(code_to_chunk, chunk.start_index)
        end_pos = offset_to_position(code_to_chunk, chunk.end_index)
        chunks_output.append(
            ChunkOutputSchema(
                text=chunk.text,
                range=Range(start=start_pos, end=end_pos),
                token_count=chunk.token_count,
            )
        )

    return chunks_output


@lru_cache(maxsize=2)
def get_RecursiveChunker(
    delimiters: tuple[str, ...] = ("----------------------------------------",),
) -> RecursiveChunker:
    rules = RecursiveRules(
        [RecursiveLevel(delimiters=list(delimiters))],
    )
    return RecursiveChunker(
        rules=rules,
    )


def chunk_docs_on_demand(
    text_to_chunk: str | list[str],
    delimiters: list[str] = ["----------------------------------------"],
) -> list[str]:
    """
    Chunks text and returns a list of strings.
    """

    chunker = get_RecursiveChunker(tuple(delimiters))
    chunks = chunker(text_to_chunk)

    # Fast flattening of list of lists
    if chunks and isinstance(chunks[0], list):
        flattened_chunks = list(chain.from_iterable(chunks))
        return list(map(attrgetter("text"), flattened_chunks))

    return list(map(attrgetter("text"), chunks))


@lru_cache(maxsize=2)
def get_SemanticChunker(
    embedding_model: str = settings.EMBEDDING_MODEL,
    chunk_size: int = 512,
) -> SemanticChunker:
    return SemanticChunker(
        chunk_size=chunk_size,
        embedding_model=embedding_model,
    )


def chunk_text_on_demand(
    text_to_chunk: str,
    embedding_model: str = settings.EMBEDDING_MODEL,
    chunk_size: int = 512,
) -> list[ChunkOutputSchema]:
    """
    Chunks text and returns a list of strings.
    """

    chunks = get_SemanticChunker(embedding_model, chunk_size).chunk(text_to_chunk)

    chunks_output = []

    for chunk in chunks:
        start_pos = offset_to_position(text_to_chunk, chunk.start_index)
        end_pos = offset_to_position(text_to_chunk, chunk.end_index)
        chunks_output.append(
            ChunkOutputSchema(
                text=chunk.text,
                range=Range(start=start_pos, end=end_pos),
                token_count=chunk.token_count,
            )
        )

    return chunks_output


def chunks_to_list_of_strings(chunks: list[ChunkOutputSchema]) -> list[str]:
    return [chunk.model_dump_json() for chunk in chunks]


def strings_to_chunks(json_strings: list[str]) -> list[ChunkOutputSchema]:
    return [ChunkOutputSchema.model_validate_json(s) for s in json_strings]


def process_chunk(chunk_text: str, role: str = "user") -> dict:
    return {"role": role, "content": chunk_text}


def format_chunks_for_memory(
    chunks: list[str], role: str = "user"
) -> list[dict[str, str]]:
    """Convert chunk objects to OpenAI message format for Mem0 (sequential)"""

    messages = [{"role": role, "content": chunk} for chunk in chunks]

    return messages
