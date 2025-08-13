from langchain_core.messages.utils import convert_to_openai_messages, AnyMessage
from src.app.config import tokenizer
from typing import Sequence


def langchain_to_pydantic(history: Sequence[AnyMessage]) -> list[dict]:
    """
    Convert LangGraph messages → OpenAI dict list for PydanticAI.
    Guarantees a list is always returned.
    """
    openai_dicts = convert_to_openai_messages(history)
    return openai_dicts if isinstance(openai_dicts, list) else [openai_dicts]


def token_count(messages: str | list[str]) -> int:
    """
    Count the number of tokens in a string or list of strings.
    """
    if isinstance(messages, str):
        messages = [messages]

    sum_tokens = 0
    for message in messages:
        sum_tokens += len(tokenizer.encode(message))
    return sum_tokens
