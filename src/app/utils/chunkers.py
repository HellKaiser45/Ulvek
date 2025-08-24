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
from src.app.utils.logger import get_logger
from src.app.tools.file_operations import offset_to_position
from src.app.agents.schemas import Range
from rank_bm25 import BM25Okapi

logger = get_logger(__name__)


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


def prefilter_bm25(
    chunks: list[str],
    queries: list[str],
    keep_per_query: int = 30,
    min_score_ratio: float | None = None,
) -> list[str]:
    """
    BM25 lexical pre-filter with optional score threshold.

    :param chunks: list of text/code snippets
    :param queries: list of query strings
    :param keep_per_query: hard upper bound of chunks returned per query
    :param min_score_ratio: optional float (0–1).  Only keep chunks whose BM25 score
        is ≥ this fraction of the best score for that query.  If None, no threshold.
    :return: deduplicated list of chunks that passed the filter
    """
    if not chunks:
        return chunks

    tokenized_corpus = [chunk.split() for chunk in chunks]
    bm25 = BM25Okapi(tokenized_corpus)

    keep_indices: set[int] = set()

    for q in queries:
        tokenized_q = q.split()
        scores = bm25.get_scores(tokenized_q)

        if min_score_ratio is not None:
            max_score = max(scores) if scores.size else 0
            threshold = max_score * min_score_ratio
            passed = [i for i, s in enumerate(scores) if s >= threshold]
            if not passed and scores.size:
                passed = [int(scores.argmax())]
            top_indices = passed[:keep_per_query]
        else:
            top_indices = sorted(
                range(len(scores)), key=lambda i: scores[i], reverse=True
            )[:keep_per_query]

        keep_indices.update(top_indices)

    filtered = [chunks[i] for i in sorted(keep_indices)]
    logger.debug(
        "BM25 filtered %d → %d chunks (keep_per_query=%d, min_score_ratio=%s)",
        len(chunks),
        len(filtered),
        keep_per_query,
        min_score_ratio,
    )
    return filtered


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
