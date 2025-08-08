from langchain_core.messages.utils import convert_to_openai_messages, AnyMessage
from src.config import tokenizer


def langchain_to_pydantic(history: list[AnyMessage]) -> dict | list[dict]:
    """
    Convert LangGraph `messages` (HumanMessage, AIMessage, ToolMessage...)
    into Pydantic-AI ModelMessage objects.
    """
    openai_dicts = convert_to_openai_messages(history)
    return openai_dicts


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
