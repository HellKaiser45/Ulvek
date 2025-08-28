from langgraph.checkpoint.memory import InMemorySaver
from litellm.types.utils import StreamingChoices, Message
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import START, END, StateGraph
import json
from src.app.agents.lite_agent_schemas import (
    AgentGraph,
    NodeName,
    ROUTING,
    FinishReason,
)
from src.app.utils.logger import get_logger
from src.app.agents.agentlite import Agent

logger = get_logger(__name__)
checkpointer = InMemorySaver()


def get_agent_from_config(config: RunnableConfig) -> Agent:
    """
    Safely retrieves the asyncio.Queue from the RunnableConfig.

    Args:
        config: The RunnableConfig passed to the LangGraph node.

    Returns:
        The event queue instance.

    Raises:
        ValueError: If the event queue is not found or is of the wrong type.
    """
    metadata = config.get("metadata")
    assert metadata, "Metadata is not found in the RunnableConfig"
    agent = metadata.get("agent")
    assert agent, "Agent is not found in the RunnableConfig's metadata"

    return agent


async def routing_edge(state: AgentGraph, config: RunnableConfig):
    return ROUTING[state.finish_reason]


async def entry_node(state: AgentGraph, config: RunnableConfig):
    agent = get_agent_from_config(config)

    result = await agent._run(state.message_history)
    choices = result.choices[0]
    assert not isinstance(choices, StreamingChoices), (
        "Streaming choices are not supported"
    )
    tool_calls = choices.message.tool_calls or []

    return_message = choices.message

    finish_reason = choices.finish_reason

    newhistory = state.message_history.copy() if state.message_history else []
    newhistory.append(return_message)
    logger.debug(f"Received response: {str(result)[:100]}...")

    return {
        "message_history": newhistory,
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
    }


async def tool_call_node(state: AgentGraph, config: RunnableConfig):
    logger.debug(f"Starting tool call node: {state.tool_calls}")
    agent = get_agent_from_config(config)
    newhistory = state.message_history.copy() if state.message_history else []

    toolused = state.tool_used.copy() if state.tool_used else []

    for tool_call in state.tool_calls:
        try:
            assert tool_call.function.name, f"""
            Tool name is not found in the tool call: {tool_call}
            For reference and future calls, please provide the tool name in the name field.
            Available tools name: {str(list(t.__name__ for t in agent.tools))}
            """
            tool_result = await agent._run_tool(
                tool_call.function.name, json.loads(tool_call.function.arguments)
            )
            logger.debug(f"Tool result: {str(tool_result)[:100]}...")

            toolused.append(tool_call.function.name)

            newhistory.append(
                Message(
                    role="tool",
                    tool_call_id=tool_call.id,
                    content=str(tool_result),
                )
            )
        except Exception as e:
            logger.warning(f"Tool call failed: {e}")
            newhistory.append(
                Message(
                    role="tool",
                    tool_call_id=tool_call.id,
                    content=f"Error: {e}",
                )
            )

    return {
        "message_history": newhistory,
        "tool_calls": [],
        "tool_used": toolused,
    }


async def structure_output_node(state: AgentGraph, config: RunnableConfig):
    logger.debug("Starting structure output node")
    agent = get_agent_from_config(config)
    working_history = state.message_history.copy() if state.message_history else []
    tool_calls = None
    args = None
    max_retries = agent.max_iterations

    if not agent.output_type:
        return {
            "message_history": working_history,
            "tool_calls": tool_calls,
            "final_answer": working_history[-1].content,
        }

    for attempt in range(max_retries):
        result = await agent._run_output(working_history)
        choices = result.choices[0]
        assert not isinstance(choices, StreamingChoices), (
            "Streaming choices are not supported"
        )
        assistant_msg = choices.message
        tool_calls = assistant_msg.tool_calls
        working_history.append(assistant_msg)

        if not tool_calls:
            if attempt == max_retries - 1:
                raise RuntimeError(f"No structured output after {max_retries} attempts")
            working_history.append(
                Message(
                    role="user",
                    content="Please provide a structured output using your tool",
                )
            )
            continue

        try:
            args = tool_calls[0].function.arguments
            agent.output_type.model_validate_json(args)
            logger.debug("✅ Structured output validated")
            working_history.append(
                Message(
                    role="tool",
                    tool_call_id=tool_calls[0].id,
                    content=str(tool_calls[0].function.arguments),
                )
            )
            break
        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"Invalid structured output after {max_retries} attempts: {e}"
                )
            logger.error(f"Structured output attempt failed: {e}")
            working_history.append(
                Message(
                    role="tool",
                    tool_call_id=tool_calls[0].id,
                    content=f"retry considering the error: {str(e)}",
                )
            )
            continue

    return {
        "message_history": working_history,
        "tool_calls": tool_calls,
        "finish_reason": FinishReason.STOP,
        "final_answer": args,
    }


agent_graph = (
    StateGraph(AgentGraph)
    .add_node(NodeName.ENTRY.value, entry_node)
    .add_node(NodeName.TOOL_CALL.value, tool_call_node)
    .add_node(NodeName.STRUCTURE_OUTPUT.value, structure_output_node)
    .add_edge(START, NodeName.ENTRY.value)
    .add_conditional_edges(NodeName.ENTRY.value, routing_edge)
    .add_edge(NodeName.STRUCTURE_OUTPUT.value, END)
    .add_edge(NodeName.TOOL_CALL.value, NodeName.ENTRY.value)
).compile(checkpointer=checkpointer)
