from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelMessage
from langchain_core.messages.utils import convert_to_openai_messages, AnyMessage


def langchain_to_pydantic(history: list[AnyMessage]) -> list[ModelMessage]:
    """
    Convert LangGraph `messages` (HumanMessage, AIMessage, ToolMessage...)
    into Pydantic-AI ModelMessage objects.
    """
    openai_dicts = convert_to_openai_messages(history)
    return ModelMessagesTypeAdapter.validate_python(openai_dicts)
