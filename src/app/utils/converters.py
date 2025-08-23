from langchain_core.messages.utils import convert_to_openai_messages
from langchain_core.messages import BaseMessage
from src.app.config import tokenizer
from typing import Sequence, Union, List, Dict, Literal, Any
import json
import uuid
from datetime import datetime
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    UserPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

OpenAIMessage = Dict[str, Any]
OpenAIMessages = List[OpenAIMessage]
MessageLikeRepresentation = Union[BaseMessage, Dict[str, Any]]


def convert_langgraph_to_openai_messages(
    langgraph_messages: Union[
        MessageLikeRepresentation, Sequence[MessageLikeRepresentation]
    ],
    text_format: Literal["string", "block"] = "string",
) -> OpenAIMessages:
    """ """

    try:
        # Call the original LangGraph conversion function
        result = convert_to_openai_messages(langgraph_messages, text_format=text_format)

        # Ensure we always return a list for consistency
        if isinstance(result, dict):
            # Single message was passed, convert to list
            validated_result = [result]
        elif isinstance(result, list):
            # Multiple messages, validate each is a dict
            validated_result = result
        else:
            raise ValueError(
                f"Unexpected return type from LangGraph converter: {type(result)}"
            )

        # Type validation - ensure each item is a proper OpenAI message dict
        for i, msg in enumerate(validated_result):
            if not isinstance(msg, dict):
                raise ValueError(
                    f"Message at index {i} is not a dictionary: {type(msg)}"
                )
            if "role" not in msg:
                raise ValueError(f"Message at index {i} missing required 'role' field")

        return validated_result

    except Exception as e:
        # Wrap any conversion errors with more context
        raise ValueError(
            f"Failed to convert LangGraph messages to OpenAI format: {e}"
        ) from e


def convert_openai_to_pydantic_messages(
    openai_messages: List[Dict[str, Any]],
) -> List[ModelMessage]:
    """
    Convert OpenAI message history to PydanticAI format.

    Args:
        openai_messages: List of OpenAI message objects with 'role' and 'content' keys.
                        Each message should have format:
                        {
                            "role": "system" | "user" | "assistant" | "tool",
                            "content": str | None,
                            "tool_calls": Optional[List[Dict]] (for assistant messages),
                            "tool_call_id": Optional[str] (for tool messages),
                            "name": Optional[str] (for tool messages)
                        }

    Returns:
        List[ModelMessage]: PydanticAI compatible message objects

    Raises:
        ValueError: If message format is invalid or unsupported role is encountered
    """
    pydantic_messages: List[ModelMessage] = []
    current_timestamp = datetime.now()

    for i, msg in enumerate(openai_messages):
        role = msg.get("role")
        content = msg.get("content")

        if not role:
            raise ValueError(f"Message at index {i} missing required 'role' field")

        # Handle system messages
        if role == "system":
            if not content:
                raise ValueError(f"System message at index {i} missing content")

            system_part = SystemPromptPart(content=content, timestamp=current_timestamp)
            request = ModelRequest(parts=[system_part])
            pydantic_messages.append(request)

        # Handle user messages
        elif role == "user":
            if not content:
                raise ValueError(f"User message at index {i} missing content")

            user_part = UserPromptPart(content=content, timestamp=current_timestamp)
            request = ModelRequest(parts=[user_part])
            pydantic_messages.append(request)

        # Handle assistant messages
        elif role == "assistant":
            parts = []

            # Add text content if present
            if content:
                text_part = TextPart(content=content)
                parts.append(text_part)

            # Add tool calls if present
            tool_calls = msg.get("tool_calls", [])
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue

                function_info = tool_call.get("function", {})
                tool_name = function_info.get("name")
                if not tool_name:
                    continue  # Skip invalid tool calls without names

                tool_args = function_info.get("arguments", "{}")
                tool_call_id = tool_call.get("id") or f"call_{i}_{len(parts)}"

                if tool_name:
                    # Parse arguments if they're a JSON string
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            # Keep as string if parsing fails
                            pass

                    tool_part = ToolCallPart(
                        tool_name=tool_name,
                        args=tool_args,
                        tool_call_id=tool_call_id or f"call_{i}_{len(parts)}",
                    )
                    parts.append(tool_part)

            if parts:
                response = ModelResponse(parts=parts, timestamp=current_timestamp)
                pydantic_messages.append(response)

        # Handle tool messages (function call results)
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id")
            tool_name = msg.get("name", "unknown_tool")

            if not tool_call_id:
                # Generate a fallback ID if missing - some OpenAI implementations omit this
                tool_call_id = f"tool_result_{i}_{uuid.uuid4().hex[:8]}"

            if content is None:
                content = ""

            # Try to parse content as JSON, fallback to string
            tool_content: Any = content
            if isinstance(content, str):
                try:
                    tool_content = json.loads(content)
                except json.JSONDecodeError:
                    # Keep as string if not valid JSON
                    tool_content = content

            tool_return_part = ToolReturnPart(
                tool_name=tool_name,
                content=tool_content,
                tool_call_id=tool_call_id,
                timestamp=current_timestamp,
            )
            request = ModelRequest(parts=[tool_return_part])
            pydantic_messages.append(request)

        else:
            raise ValueError(f"Unsupported message role '{role}' at index {i}")

    return pydantic_messages


def convert_pydantic_to_openai_messages(
    pydantic_messages: List[ModelMessage],
) -> List[Dict[str, Any]]:
    """
    Convert PydanticAI message history back to OpenAI format.

    Args:
        pydantic_messages: List of PydanticAI ModelMessage objects

    Returns:
        List[Dict[str, Any]]: OpenAI compatible message objects
    """
    openai_messages: List[Dict[str, Any]] = []

    for msg in pydantic_messages:
        if msg.kind == "request":
            # Handle ModelRequest
            for part in msg.parts:
                if part.part_kind == "system-prompt":
                    openai_messages.append({"role": "system", "content": part.content})
                elif part.part_kind == "user-prompt":
                    openai_messages.append({"role": "user", "content": part.content})
                elif part.part_kind == "tool-return":
                    # Convert tool return to OpenAI tool message format
                    content = part.content
                    if not isinstance(content, str):
                        content = json.dumps(content)

                    openai_messages.append(
                        {
                            "role": "tool",
                            "content": content,
                            "tool_call_id": part.tool_call_id,
                            "name": part.tool_name,
                        }
                    )

        elif msg.kind == "response":
            # Handle ModelResponse
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            tool_calls = []
            text_content = []

            for part in msg.parts:
                if part.part_kind == "text":
                    text_content.append(part.content)
                elif part.part_kind == "tool-call":
                    # Convert to OpenAI tool call format
                    args = part.args
                    if not isinstance(args, str):
                        args = json.dumps(args)

                    tool_calls.append(
                        {
                            "id": part.tool_call_id,
                            "type": "function",
                            "function": {"name": part.tool_name, "arguments": args},
                        }
                    )

            # Set content
            if text_content:
                assistant_msg["content"] = "".join(text_content)
            else:
                assistant_msg["content"] = None

            # Add tool calls if present
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls

            openai_messages.append(assistant_msg)

    return openai_messages


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


def truncate_content_by_tokens(content: str, max_tokens: int) -> str:
    """
    Truncate content to fit within max_tokens by binary search on content length.

    Args:
        content: Text content to truncate
        max_tokens: Maximum allowed tokens

    Returns:
        Truncated content that fits within token limit
    """
    if token_count(content) <= max_tokens:
        return content

    # Binary search to find the right character position
    left, right = 0, len(content)

    while left < right:
        mid = (left + right + 1) // 2
        if token_count(content[:mid]) <= max_tokens:
            left = mid
        else:
            right = mid - 1

    return content[:left]
