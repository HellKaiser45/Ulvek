import inspect
from typing import Any, Callable, get_type_hints, Type, Union, get_origin, get_args
from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema
import json
import asyncio
from src.app.utils.logger import get_logger
from pathlib import Path

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
    """Clean, simple tool schema generation with PydanticAI optimizations."""

    @staticmethod
    def get_pydantic_param(func: Callable) -> tuple[str, type] | None:
        """Find single Pydantic model parameter, if any."""
        sig = inspect.signature(func)
        hints = get_type_hints(func)

        pydantic_params = [
            (name, hints.get(name, param.annotation))
            for name, param in sig.parameters.items()
            if ToolSchemaGenerator._is_pydantic_model(hints.get(name, param.annotation))
        ]

        return pydantic_params[0] if len(pydantic_params) == 1 else None

    @staticmethod
    def _is_pydantic_model(annotation: type) -> bool:
        """Check if annotation is a Pydantic model."""
        return inspect.isclass(annotation) and issubclass(annotation, BaseModel)

    @staticmethod
    def function_to_tool(func: Callable) -> dict[str, Any]:
        """Convert function to OpenAI tool format with PydanticAI optimizations."""
        sig = inspect.signature(func)
        hints = get_type_hints(func)

        properties = {}
        required = []

        for name, param in sig.parameters.items():
            annotation = hints.get(name, param.annotation)

            if ToolSchemaGenerator._is_pydantic_model(annotation):
                prop_schema = annotation.model_json_schema(
                    schema_generator=GenerateToolJsonSchema
                )
            else:
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
    def _type_to_schema(annotation: Type) -> dict[str, Any]:
        """Convert Python type to JSON schema, handling unions and custom types."""
        # Handle Union types
        if get_origin(annotation) is Union:
            args = get_args(annotation)
            # Filter out None types (Optional)
            non_none_args = [arg for arg in args if arg is not type(None)]
            if non_none_args:
                # Use the first non-None type
                return ToolSchemaGenerator._type_to_schema(non_none_args[0])

        # Handle specific types
        if annotation is Path or (
            inspect.isclass(annotation) and issubclass(annotation, Path)
        ):
            return {"type": "string", "description": "File path"}

        type_mapping = {
            str: {"type": "string"},
            int: {"type": "integer"},
            float: {"type": "number"},
            bool: {"type": "boolean"},
            list: {"type": "array"},
            dict: {"type": "object"},
            type(None): {"type": "null"},
        }

        # Handle custom types with __name__
        if hasattr(annotation, "__name__"):
            if annotation.__name__ == "FilePath":
                return {"type": "string", "description": "File path"}

        return type_mapping.get(annotation, {"type": "string"})

    @staticmethod
    async def call_with_pydantic_handling(func: Callable, args: dict[str, Any]) -> Any:
        """Execute function with automatic Pydantic model instantiation."""
        pydantic_param = ToolSchemaGenerator.get_pydantic_param(func)

        if pydantic_param:
            param_name, param_type = pydantic_param
            model_data = args.get(param_name, args)
            if isinstance(model_data, str):
                try:
                    model_data = json.loads(model_data)
                except json.JSONDecodeError:
                    pass

            if not isinstance(model_data, dict):
                raise ValueError(
                    f"Expected dict for {param_type.__name__}, got {type(model_data)}"
                )

            try:
                model_instance = param_type(**model_data)
                call_args = {param_name: model_instance}
            except Exception as e:
                logger.error(f"Failed to instantiate {param_type.__name__}: {e}")
                raise ValueError(f"Invalid arguments for {param_type.__name__}: {e}")
        else:
            call_args = args

        if asyncio.iscoroutinefunction(func):
            return await func(**call_args)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(**call_args))


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
