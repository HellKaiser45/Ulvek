import inspect
from typing import Any, Callable, get_type_hints, Type, Union, get_origin, get_args
from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema
import json
import asyncio
from pathlib import Path
from src.app.utils.logger import get_logger

logger = get_logger(__name__)


class GenerateToolJsonSchema(GenerateJsonSchema):
    """Optimized schema generator for LLM tools - removes unnecessary fields."""

    def _named_required_fields_schema(self, named_required_fields) -> dict[str, Any]:
        """Remove property titles that clutter tool schemas."""
        schema = super()._named_required_fields_schema(named_required_fields)
        for prop in schema.get("properties", {}):
            schema["properties"][prop].pop("title", None)
        return schema


class ToolSchemaGenerator:
    """Clean, simple tool schema generation with proper type handling."""

    @staticmethod
    def _is_pydantic_model(annotation: type) -> bool:
        """Check if annotation is a Pydantic model."""
        return inspect.isclass(annotation) and issubclass(annotation, BaseModel)

    @staticmethod
    def _is_path_like(annotation: type) -> bool:
        """Check if annotation is Path-like."""
        if annotation is Path:
            return True
        if inspect.isclass(annotation) and issubclass(annotation, Path):
            return True
        if hasattr(annotation, "__name__") and annotation.__name__ == "FilePath":
            return True
        return False

    @staticmethod
    def _resolve_union_type(annotation: type) -> tuple[type, bool]:
        """Resolve Union types, returning (resolved_type, is_optional)."""
        if get_origin(annotation) is Union:
            args = get_args(annotation)
            none_type = type(None)

            # Check if it's Optional (Union with None)
            is_optional = none_type in args
            non_none_args = [arg for arg in args if arg is not none_type]

            if len(non_none_args) == 1:
                return non_none_args[0], is_optional
            elif len(non_none_args) > 1:
                # For complex unions like Path | FilePath, prefer Path-like types
                for arg in non_none_args:
                    if ToolSchemaGenerator._is_path_like(arg):
                        return arg, is_optional
                # Otherwise return first non-None type
                return non_none_args[0], is_optional

        return annotation, False

    @staticmethod
    def _type_to_schema(annotation: Type) -> dict[str, Any]:
        """Convert Python type to JSON schema with proper Union handling."""
        resolved_type, is_optional = ToolSchemaGenerator._resolve_union_type(annotation)

        # Handle Path-like types
        if ToolSchemaGenerator._is_path_like(resolved_type):
            return {"type": "string", "description": "File path"}

        # Handle Pydantic models
        if ToolSchemaGenerator._is_pydantic_model(resolved_type):
            return resolved_type.model_json_schema(
                schema_generator=GenerateToolJsonSchema
            )

        # Handle basic types
        type_mapping = {
            str: {"type": "string"},
            int: {"type": "integer"},
            float: {"type": "number"},
            bool: {"type": "boolean"},
            list: {"type": "array"},
            dict: {"type": "object"},
        }

        return type_mapping.get(resolved_type, {"type": "string"})

    @staticmethod
    def _convert_argument(value: Any, target_type: type) -> Any:
        """Convert argument to target type if needed."""
        resolved_type, _ = ToolSchemaGenerator._resolve_union_type(target_type)

        # Convert string to Path-like
        if ToolSchemaGenerator._is_path_like(resolved_type) and isinstance(value, str):
            if resolved_type is Path or (
                inspect.isclass(resolved_type) and issubclass(resolved_type, Path)
            ):
                return Path(value)
            # For custom FilePath types, assume they accept string in constructor
            return resolved_type(value)

        # Handle Pydantic models
        if ToolSchemaGenerator._is_pydantic_model(resolved_type):
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            if isinstance(value, dict):
                return resolved_type(**value)

        return value

    @staticmethod
    def function_to_tool(func: Callable) -> dict[str, Any]:
        """Convert function to OpenAI tool format with proper type handling."""
        sig = inspect.signature(func)
        hints = get_type_hints(func)
        properties = {}
        required = []

        for name, param in sig.parameters.items():
            annotation = hints.get(name, param.annotation)
            prop_schema = ToolSchemaGenerator._type_to_schema(annotation)
            properties[name] = prop_schema

            if param.default is inspect.Parameter.empty:
                required.append(name)
            else:
                properties[name]["default"] = param.default

        return {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": (func.__doc__ or "").strip(),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    @staticmethod
    async def call_with_type_conversion(func: Callable, args: dict[str, Any]) -> Any:
        """Execute function with automatic type conversion."""
        sig = inspect.signature(func)
        hints = get_type_hints(func)
        converted_args = {}

        for param_name, param in sig.parameters.items():
            if param_name in args:
                target_type = hints.get(param_name, param.annotation)
                converted_value = ToolSchemaGenerator._convert_argument(
                    args[param_name], target_type
                )
                converted_args[param_name] = converted_value
            elif param.default is not inspect.Parameter.empty:
                converted_args[param_name] = param.default

        if asyncio.iscoroutinefunction(func):
            return await func(**converted_args)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(**converted_args))


def create_output_tool(output_type: Type[BaseModel]) -> dict[str, Any]:
    """Create optimized output tool schema."""
    return {
        "type": "function",
        "function": {
            "name": "return_response",
            "description": "Return a structured output to the user",
            "parameters": output_type.model_json_schema(
                schema_generator=GenerateToolJsonSchema
            ),
        },
    }
