from typing import Callable, Any, TypeVar, Generic
from litellm.types.utils import ModelResponse, Message
from src.app.agents.prompts.chat import CONVERSATIONAL_AGENT_PROMPT
from src.app.agents.prompts.reviewer import REVIEWER_AGENT_PROMPT
from src.app.agents.prompts.orchestrator import ORCHESTRATOR_AGENT_PROMPT
from src.app.agents.prompts.context_retriever import CONTEXT_RETRIEVER_PROMPT
from src.app.agents.prompts.worker import CODING_AGENT_FULL_PROMPT
from src.app.agents.prompts.task_classification import CLASSIFIER_AGENT_PROMPT
from src.app.agents.lite_agent_schemas import AgentGraph
from src.app.agents.schemas import (
    GatheredContext,
    Evaluation,
    ProjectPlan,
    TaskType,
    FilePlan,
)
from src.app.utils.logger import get_logger
from src.app.utils.schema_generator import ToolSchemaGenerator, create_output_tool
from src.app.workflow.utils import build_static
from litellm import acompletion
from src.app.tools.file_operations import (
    get_line_content,
    get_range_content,
    read_file_content,
    find_text_in_file,
)
from src.app.tools.interactive_tools import gather_docs_context
from src.app.tools.search_files import similarity_search, search_files
from src.app.config import settings
from pydantic import BaseModel, Field
import litellm
import uuid


logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class Agent(BaseModel, Generic[T]):
    name: str
    tools: list[Callable] = Field(default_factory=list)
    output_type: type[T] | None = None
    system_prompt: str
    model: str = settings.MODEL_NAME
    provider: str = settings.PROVIDER
    api_key: str = settings.OPENROUTER_API_KEY.get_secret_value()
    max_iterations: int = 5
    tool_registry: dict[str, Callable] = Field(default_factory=dict)
    tool_schemas: list[dict] = Field(default_factory=list)

    def model_post_init(self, __context):
        self.tool_registry = {t.__name__: t for t in self.tools}
        self.tool_schemas = [
            ToolSchemaGenerator.function_to_tool(t) for t in self.tools
        ]

    async def _run(self, message_history: list[Message]):
        litellm.api_key = self.api_key
        logger.debug("starting acompletion")

        completion_kwargs: dict[str, Any] = dict(
            model=self.provider + "/" + self.model,
            messages=message_history,
            num_retries=3,
        )
        if self.tools:
            completion_kwargs["tools"] = self.tool_schemas
            completion_kwargs["tool_choice"] = "auto"

        try:
            response = await acompletion(**completion_kwargs)
        except Exception as e:
            logger.debug(f"Error when completing with acompletion: {e}")
            raise e
        assert isinstance(response, ModelResponse)

        return response

    async def _run_output(self, message_history: list[Message]):
        litellm.api_key = self.api_key
        assert self.output_type, "Output type is not defined which is not a valid case"
        fake_tool = create_output_tool(self.output_type)

        response = await acompletion(
            model=self.provider + "/" + self.model,
            tools=[fake_tool],
            tool_choice="required",
            messages=message_history,
            temperature=0,
            num_retries=3,
        )

        assert isinstance(response, ModelResponse)

        return response

    async def _run_tool(self, name: str, args: dict[str, Any]) -> Any:
        """
        Execute a tool with automatic Pydantic model handling.
        This elegantly handles:
        - Complex nested Pydantic models
        - Simple parameter functions
        - **kwargs functions
        """

        if name not in self.tool_registry:
            raise ValueError(
                f"Tool '{name}' not found in registry. "
                f"Available: {list(self.tool_registry.keys())}"
            )
        tool_func = self.tool_registry[name]

        try:
            return await ToolSchemaGenerator.call_with_type_conversion(tool_func, args)
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}")
            raise e

    async def run(
        self,
        prompt: str,
        message_history: list[dict[str, Any]] | None = None,
    ) -> T | str:
        from src.app.agents.agent_graph import agent_graph
        from langchain_core.runnables.config import RunnableConfig

        if self.output_type is None:
            raise ValueError("output_type not set")

        conversation_id = uuid.uuid4()
        message_history = message_history or []

        messages_list: list[dict[str, Any]] = [
            dict(role="system", content=self.system_prompt),
        ]

        if message_history:
            messages_list.extend(message_history)

        else:
            messages_list.append(
                dict(
                    role="user",
                    content=prompt,
                )
            )

        try:
            InitialState = AgentGraph(
                message_history=[Message(**m) for m in messages_list],
            )
            config: RunnableConfig = {
                "configurable": {"thread_id": conversation_id},
                "run_id": conversation_id,
                "metadata": {"agent": self},
            }

            graph = None
            async for chunk in agent_graph.astream(
                InitialState, config=config, stream_mode="values"
            ):
                graph = chunk

            valid_graph = AgentGraph.model_validate(graph)

            if self.output_type:
                return self.output_type.model_validate_json(valid_graph.final_answer)
            else:
                return valid_graph.final_answer

        except Exception as e:
            logger.debug(f"Error when running agent graph: {e}")
            raise e


task_classification_agent: Agent[TaskType] = Agent(
    system_prompt=CLASSIFIER_AGENT_PROMPT,
    name="task_classification_agent",
    output_type=TaskType,
)

evaluator_agent = Agent(
    system_prompt=(REVIEWER_AGENT_PROMPT),
    output_type=Evaluation,
    name="evaluator_agent",
)

coding_agent = Agent(
    system_prompt=(CODING_AGENT_FULL_PROMPT),
    name="coding_agent",
    output_type=FilePlan,
    tools=[
        read_file_content,
        get_line_content,
        get_range_content,
        find_text_in_file,
    ],
)

orchestrator_agent = Agent(
    system_prompt=(ORCHESTRATOR_AGENT_PROMPT),
    output_type=ProjectPlan,
    name="orchestrator_agent",
)

context_retriever_agent = Agent(
    system_prompt=(CONTEXT_RETRIEVER_PROMPT),
    name="context_gatherer_agent",
    output_type=GatheredContext,
    tools=[
        search_files,
        similarity_search,
        gather_docs_context,
    ],
)

conversational_agent = Agent(
    system_prompt=(CONVERSATIONAL_AGENT_PROMPT),
    name="conversational_agent",
)


async def main(prompt: str):
    project_context = await build_static()
    prompt = f"""
    ## Project structure
    {project_context}
    ---
    gather context for the following user request:
    {prompt}
    """
    context_agent = Agent(
        name="context_agent",
        tools=[search_files, similarity_search, gather_docs_context],
        output_type=GatheredContext,
        system_prompt=CONTEXT_RETRIEVER_PROMPT,
    )
    final_result = await context_agent.run(prompt)

    return final_result


if __name__ == "__main__":
    import asyncio

    input_prompt = input("Enter a prompt: ")
    asyncio.run(main(input_prompt))
