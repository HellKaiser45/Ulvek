"""
src/workflow/graph.py

Enhanced LangGraph + PydanticAI orchestrator-worker workflow
with sequential task execution, improved error handling, detailed logging,
and task-specific conversation history between worker and reviewer.
"""

from __future__ import annotations
import operator
import logging
import time  # For timing
from typing import Annotated, TypedDict, Literal, List, Dict, Any, Optional, NamedTuple
from langgraph.graph import START, END, StateGraph

# from langgraph.types import Send # Not needed for sequential execution
from pathlib import Path

# Import the centralized logger and context size utility
from src.utils.logger import get_logger, log_context_size
from src.agents.agent import (
    orchestrator_agent,
    coding_agent,
    evaluator_agent,
    context_retriever_agent,
    conversational_agent,
)
from src.tools.memory import m as memory
from src.tools.prompt_eval import predictor
from src.tools.codebase import process_file, get_non_ignored_files
from pydantic_ai import capture_run_messages, UnexpectedModelBehavior

# ------------------------------------------------------------------
# 1. Logger setup
# ------------------------------------------------------------------
logger = get_logger(__name__)

# ------------------------------------------------------------------
# 2. Task History Definition
# ------------------------------------------------------------------


class TaskInteraction(NamedTuple):
    """Represents one interaction (attempt + feedback) for a task."""

    task_content: str  # The original task description
    attempt_output: str  # The agent's output for that attempt
    feedback: str  # The reviewer's feedback on that output


# ------------------------------------------------------------------
# 3. Unified state definition (Updated for sequential execution and task history)
# ------------------------------------------------------------------
class State(TypedDict):
    """
    Shared workflow state passed between graph nodes.
    """

    prompt: str  # Original user prompt
    static_ctx: str  # Markdown snapshot of codebase
    dynamic_ctx: str  # Retrieved, task-specific context
    tasks: Annotated[List[str], operator.add]  # List of tasks
    current_task_index: int  # Index of the next task to process
    results: Annotated[Dict[str, str], lambda x, y: {**x, **y}]  # Task results
    completed: Annotated[
        Dict[str, str], lambda x, y: {**x, **y}
    ]  # Completed task results
    final_result: str  # Aggregated outputs when done
    route: Literal["chat", "need_context", "heavy", "default"]
    # Task-specific conversation history
    task_histories: Annotated[Dict[str, List[TaskInteraction]], lambda x, y: {**x, **y}]


# ------------------------------------------------------------------
# 4. Router: choose chat vs. code paths (Updated based on CSV analysis)
# ------------------------------------------------------------------
async def router(state: State) -> dict[str, str]:
    """
    Decide execution path based on prompt evaluation.
    """
    logger.info(
        "🔍 Routing prompt: %s",
        state["prompt"][:100] + "..."
        if len(state["prompt"]) > 100
        else state["prompt"],
    )
    start_time = time.time()
    evals = predictor(state["prompt"])
    logger.debug("📊 Prompt evaluation: %s", evals)
    elapsed_time = time.time() - start_time
    logger.debug("⏱️  Prompt evaluation took %.2f seconds", elapsed_time)

    # Extract values (handling list format from predictor)
    task_type_prob = (
        evals["task_type_prob"][0]
        if isinstance(evals["task_type_prob"], list)
        else evals["task_type_prob"]
    )
    reasoning = (
        evals["reasoning"][0]
        if isinstance(evals["reasoning"], list)
        else evals["reasoning"]
    )
    contextual_knowledge = (
        evals["contextual_knowledge"][0]
        if isinstance(evals["contextual_knowledge"], list)
        else evals["contextual_knowledge"]
    )
    creativity = (
        evals["creativity_scope"][0]
        if isinstance(evals["creativity_scope"], list)
        else evals["creativity_scope"]
    )
    domain_knowledge = (
        evals["domain_knowledge"][0]
        if isinstance(evals["domain_knowledge"], list)
        else evals["domain_knowledge"]
    )

    # Chat path: High task probability, very low reasoning needed
    if task_type_prob > 0.9 and reasoning < 0.01:
        route = "chat"
        logger.info("🛣️  Routing to chat path")
    # Need context path: When contextual knowledge is needed or domain knowledge is high
    elif (
        contextual_knowledge > 0.3  # Moderate to high contextual knowledge
        or domain_knowledge > 0.8  # High domain knowledge
        or (
            task_type_prob > 0.5 and contextual_knowledge > 0.2
        )  # Medium task with some context need
    ):
        route = "need_context"
        logger.info(
            "🛣️  Routing to context-aware path (contextual_knowledge=%.3f, domain_knowledge=%.3f)",
            contextual_knowledge,
            domain_knowledge,
        )
    # Heavy computation path: Low creativity, low context, but high reasoning
    elif creativity < 0.5 and contextual_knowledge < 0.5 and reasoning > 0.2:
        route = "heavy"
        logger.info("🛣️  Routing to heavy computation path")
    # Default path: Planning for code generation or complex tasks
    else:
        route = "default"
        logger.info("🛣️  Routing to default planning path")
        logger.debug(
            "🔍 Routing details - task_type_prob: %.3f, reasoning: %.3f, contextual_knowledge: %.3f, creativity: %.3f",
            task_type_prob,
            reasoning,
            contextual_knowledge,
            creativity,
        )

    return {"route": route}


# ------------------------------------------------------------------
# 5. Static snapshot builder (Enhanced logging)
# ------------------------------------------------------------------
async def build_static_snapshot() -> str:
    """
    Scan codebase files and return a markdown overview.
    """
    logger.info("📁 Building static codebase snapshot")
    start_time = time.time()
    files = await get_non_ignored_files()
    logger.debug("📄 Found %d files to analyze", len(files))

    analyses = await process_file(files)
    elapsed_time = time.time() - start_time
    logger.info(
        "✅ Processed %d files for static context in %.2f seconds",
        len(analyses),
        elapsed_time,
    )

    snapshot = "\n".join(
        f"- **{fa.file_path}** (`{fa.file_type}`): {fa.description}" for fa in analyses
    )
    log_context_size(logger, snapshot, "Static codebase snapshot")
    return snapshot


# ------------------------------------------------------------------
# 6. Graph node implementations (Updated for sequential execution, enhanced logging/error handling, and task history)
# ------------------------------------------------------------------
async def refresh_static(state: State) -> dict[str, str]:
    """
    Update static context after code changes.
    """
    logger.info("🔄 Refreshing static context")
    start_time = time.time()
    static_ctx = await build_static_snapshot()
    elapsed_time = time.time() - start_time
    logger.debug(
        "📦 Static context updated (%d chars) in %.2f seconds",
        len(static_ctx),
        elapsed_time,
    )
    return {"static_ctx": static_ctx}


async def context_provider(state: State) -> dict[str, str]:
    """
    Gather dynamic context relevant to the prompt.
    """
    logger.info("🔍 Retrieving dynamic context")
    log_context_size(logger, state["prompt"], "User prompt for context retrieval")
    log_context_size(
        logger, state["static_ctx"], "Static context for context retrieval"
    )

    enriched_prompt = (
        f"Static overview:\n{state['static_ctx']}\n\nUser request: {state['prompt']}"
    )
    log_context_size(logger, enriched_prompt, "Full context provider prompt")

    start_time = time.time()
    with capture_run_messages() as messages:
        try:
            enriched = await context_retriever_agent.run(enriched_prompt)
            elapsed_time = time.time() - start_time
            logger.info(
                "✅ Dynamic context retrieved (%d chars) in %.2f seconds",
                len(enriched.output),
                elapsed_time,
            )
            log_context_size(logger, enriched.output, "Retrieved dynamic context")
            return {"dynamic_ctx": enriched.output}
        except UnexpectedModelBehavior as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Model error in context provider after %.2f seconds: %s",
                elapsed_time,
                e,
            )
            logger.debug("📝 Message history: %s", messages)
            # Provide fallback context
            fallback_context = "Context retrieval failed due to model error. Proceeding with available information."
            logger.info("🔄 Using fallback context")
            return {"dynamic_ctx": fallback_context}
        except Exception as e:  # Catch other potential errors
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Unexpected error in context provider after %.2f seconds: %s",
                elapsed_time,
                e,
                exc_info=True,
            )
            return {
                "dynamic_ctx": "Context retrieval failed due to an unexpected error."
            }


async def chat(state: State) -> dict[str, str]:
    """
    Fallback conversational agent path.
    """
    logger.info("💬 Engaging conversational agent")
    log_context_size(logger, state["prompt"], "Chat prompt")

    start_time = time.time()
    with capture_run_messages() as messages:
        try:
            run = await conversational_agent.run(state["prompt"])
            elapsed_time = time.time() - start_time
            memory.add(
                [{"role": "assistant", "content": run.output}], user_id="workflow"
            )
            logger.info(
                "✅ Chat response generated (%d chars) in %.2f seconds",
                len(run.output),
                elapsed_time,
            )
            log_context_size(logger, run.output, "Chat response")
            return {"final_result": run.output}
        except UnexpectedModelBehavior as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Model error in chat agent after %.2f seconds: %s", elapsed_time, e
            )
            logger.debug("📝 Message history: %s", messages)
            error_response = (
                f"Sorry, I encountered an issue processing your request: {str(e)}"
            )
            return {"final_result": error_response}
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Unexpected error in chat agent after %.2f seconds: %s",
                elapsed_time,
                e,
                exc_info=True,
            )
            return {"final_result": "Sorry, an unexpected error occurred."}


async def plan(state: State) -> dict[str, Any]:  # Return type updated
    """
    Decompose user prompt into ordered to-do tasks.
    """
    logger.info("📋 Planning tasks from user request")
    log_context_size(logger, state["prompt"], "User prompt for planning")
    log_context_size(logger, state["static_ctx"], "Static context for planning")
    log_context_size(logger, state["dynamic_ctx"], "Dynamic context for planning")

    prompt = (
        f"{state['static_ctx']}\n\n"
        f"{state['dynamic_ctx']}\n\n"
        f"User request: {state['prompt']}"
    )
    log_context_size(logger, prompt, "Full planning prompt")

    start_time = time.time()
    with capture_run_messages() as messages:
        try:
            run = await orchestrator_agent.run(prompt)
            elapsed_time = time.time() - start_time
            # Handle potential variations in orchestrator output structure
            raw_tasks = getattr(
                run.output, "tasks", []
            )  # Assume output has a 'tasks' attribute
            if not raw_tasks:
                logger.warning(
                    "⚠️  Planner returned no tasks. Checking output directly."
                )
                raw_tasks = [str(run.output)] if run.output else []

            # If tasks contain checklist items, split them into individual tasks
            individual_tasks: List[str] = []
            for task_item in raw_tasks:
                # Convert task to string if it's not already
                task_str: str = (
                    task_item if isinstance(task_item, str) else str(task_item)
                )
                if "- [ ]" in task_str:
                    # Split checklist into individual tasks
                    checklist_items = [
                        line.strip()[6:]  # Remove "- [ ] " prefix
                        for line in task_str.split("\n")
                        if line.strip().startswith("- [ ]")
                    ]
                    individual_tasks.extend(checklist_items)
                else:
                    individual_tasks.append(task_str)

            logger.info(
                "✅ Generated %d individual tasks in %.2f seconds: %s",
                len(individual_tasks),
                elapsed_time,
                individual_tasks[:5] if len(individual_tasks) > 5 else individual_tasks,
            )
            # Return tasks list and initialize index for sequential processing
            # Also initialize task_histories dictionary
            return {
                "tasks": individual_tasks,
                "current_task_index": 0,
                "task_histories": {},
            }
        except UnexpectedModelBehavior as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Model error in planner after %.2f seconds: %s", elapsed_time, e
            )
            logger.debug("📝 Message history: %s", messages)
            # Return an empty task list to prevent downstream errors, or handle as needed
            return {
                "tasks": [
                    f"Error during planning: {str(e)}. Please rephrase your request."
                ],
                "current_task_index": 0,
                "task_histories": {},
            }
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Unexpected error in planner after %.2f seconds: %s",
                elapsed_time,
                e,
                exc_info=True,
            )
            return {
                "tasks": ["An unexpected error occurred during task planning."],
                "current_task_index": 0,
                "task_histories": {},
            }


# --- Sequential Execution Logic ---
async def route_to_worker_or_end(state: State) -> str:
    """
    Conditional edge: Decide whether to process the next task or end.
    """
    if state["current_task_index"] < len(state["tasks"]):
        logger.info(
            "➡️  Routing to process task %d/%d",
            state["current_task_index"] + 1,
            len(state["tasks"]),
        )
        return "process_task"
    else:
        logger.info("🔚 All tasks processed, routing to collect results")
        return "collect"


async def process_task(state: State) -> dict[str, str]:
    """
    Prepare the prompt for the current task and send it to the worker.
    This node sets the 'prompt' state key to the current task content.
    """
    task_index = state["current_task_index"]
    task_content = state["tasks"][task_index]
    logger.info(
        "📤 Preparing task %d/%d for worker: %s",
        task_index + 1,
        len(state["tasks"]),
        task_content[:80] + "..." if len(task_content) > 80 else task_content,
    )
    # The 'worker' node expects the task content in the 'prompt' key
    return {"prompt": task_content}


async def worker(state: State) -> dict[str, Any]:  # Return type updated
    """
    Execute the current task (content is in state['prompt']) using the coding agent.
    Incorporates task-specific history into the prompt.
    """
    task_content = state["prompt"]  # Get task content prepared by process_task
    task_index = state.get("current_task_index", 0)  # Get current index for logging
    task_count = len(state.get("tasks", []))
    logger.info(
        "⚙️  Worker executing task %d/%d: %s",
        task_index + 1,
        task_count,
        task_content[:80] + "..." if len(task_content) > 80 else task_content,
    )

    # Retrieve task history
    task_history = state.get("task_histories", {}).get(task_content, [])
    history_summary = ""
    if task_history:
        logger.debug(
            "📜 Found %d previous interactions for this task.", len(task_history)
        )
        history_parts = []
        for i, interaction in enumerate(task_history):
            history_parts.append(
                f"Attempt {i + 1}:\n"
                f"Output: {interaction.attempt_output[:200]}{'...' if len(interaction.attempt_output) > 200 else ''}\n"
                f"Feedback: {interaction.feedback}"
            )
        history_summary = (
            "\n\n--- Previous Attempts and Feedback ---\n"
            + "\n---\n".join(history_parts)
            + "\n---\n"
        )

    # Log context sizes before building the full prompt
    log_context_size(logger, task_content, "Current task content")
    log_context_size(logger, state["static_ctx"], "Static context for worker")
    log_context_size(logger, state["dynamic_ctx"], "Dynamic context for worker")

    # Build the prompt, including history if available
    prompt = (
        f"Static files:\n{state['static_ctx']}\n\n"
        f"Dynamic context:\n{state['dynamic_ctx']}\n\n"
        f"Task: {task_content}"
    )
    if history_summary:
        prompt += f"\n\n{history_summary}"
        prompt += "Please consider the feedback from previous attempts when generating your response for this task."

    log_context_size(logger, prompt, "Full worker prompt (with history)")

    start_time = time.time()
    with capture_run_messages() as messages:
        try:
            code_run = await coding_agent.run(prompt)
            elapsed_time = time.time() - start_time
            logger.info(
                "✅ Task %d completed (%d chars output) in %.2f seconds",
                task_index + 1,
                len(code_run.output),
                elapsed_time,
            )
            log_context_size(logger, code_run.output, "Worker task output")
            # Return the result and increment the task index for the next iteration
            return {
                "results": {task_content: code_run.output},
                "current_task_index": task_index + 1,  # Move to next task
            }
        except UnexpectedModelBehavior as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Model error in worker for task %d after %.2f seconds: %s",
                task_index + 1,
                elapsed_time,
                e,
            )
            logger.debug("📝 Message history: %s", messages)
            error_result = f"Error executing task: {str(e)}"
            return {
                "results": {task_content: error_result},
                "current_task_index": task_index + 1,  # Still move to next task
            }
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Unexpected error in worker for task %d after %.2f seconds: %s",
                task_index + 1,
                elapsed_time,
                e,
                exc_info=True,
            )
            error_result = "An unexpected error occurred while executing this task."
            return {
                "results": {task_content: error_result},
                "current_task_index": task_index + 1,  # Still move to next task
            }


async def review(state: State) -> dict[str, Any]:  # Return type updated
    """
    Review the latest worker's output.
    If failed, store the interaction history for the task and signal a retry.
    If passed, mark as complete.
    """
    # Get the last processed task and its result
    task_index = (
        state["current_task_index"] - 1
    )  # Index of the task just completed by worker
    if task_index < 0 or task_index >= len(state["tasks"]):
        logger.error("❌ Invalid task index for review: %d", task_index)
        return {"current_task_index": task_index + 1}  # Move on

    task_content = state["tasks"][task_index]
    if task_content not in state["results"]:
        logger.error("❌ Task result not found for review: %s", task_content)
        return {"current_task_index": task_index + 1}  # Move on

    code = state["results"][task_content]
    logger.info(
        "🔍 Reviewing task %d: %s",
        task_index + 1,
        task_content[:80] + "..." if len(task_content) > 80 else task_content,
    )
    logger.debug("📝 Code to review (%d chars)", len(code))
    log_context_size(logger, code, "Code output for review")

    review_prompt = f"Task: {task_content}\nCode/Output:\n{code}"
    log_context_size(logger, review_prompt, "Full review prompt")

    start_time = time.time()
    with capture_run_messages() as messages:
        try:
            review_run = await evaluator_agent.run(review_prompt)
            elapsed_time = time.time() - start_time
            grade = getattr(review_run.output, "grade", "fail").lower()
            logger.debug(
                "📊 Review result for task %d: grade=%s in %.2f seconds",
                task_index + 1,
                grade,
                elapsed_time,
            )

            # Access feedback attribute safely
            feedback = getattr(
                review_run.output, "feedback", "No specific feedback provided."
            )

            if grade == "pass":
                logger.info("✅ Task %d passed review", task_index + 1)
                memory.add(
                    [{"role": "assistant", "content": f"Task: {task_content}\n{code}"}],
                    user_id="workflow",
                )
                # Clear history for this task as it's complete (optional, saves state size)
                # task_histories_update = {task_content: []}
                return {"completed": {task_content: code}}
                # Note: current_task_index is already incremented by worker, so we don't change it here.

            else:  # Includes 'fail' and 'revision_needed'
                logger.warning(
                    "❌ Task %d failed review (grade: %s), preparing for retry",
                    task_index + 1,
                    grade,
                )
                logger.debug("📝 Feedback: %s", feedback)

                # --- Store interaction history for this task ---
                # Create a new interaction record
                new_interaction = TaskInteraction(
                    task_content=task_content, attempt_output=code, feedback=feedback
                )

                # Get existing history for this task
                current_history = state.get("task_histories", {}).get(task_content, [])
                # Append the new interaction
                updated_history = current_history + [new_interaction]

                logger.info(
                    "💾 Stored feedback for task %d. Total interactions: %d",
                    task_index + 1,
                    len(updated_history),
                )

                # Signal to retry the same task by decrementing the index
                # and update the task history in the state
                return {
                    # Signal retry by keeping the same task
                    "tasks": [task_content],
                    "current_task_index": task_index,  # Retry the same task index
                    # Update the task history for this specific task
                    "task_histories": {task_content: updated_history},
                    # Optionally, we could also update dynamic_ctx with feedback,
                    # but the history is now passed directly in the prompt.
                    # "dynamic_ctx": f"Previous feedback for this task: {feedback}",
                }
        except UnexpectedModelBehavior as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Model error in reviewer for task %d after %.2f seconds: %s",
                task_index + 1,
                elapsed_time,
                e,
            )
            logger.debug("📝 Message history: %s", messages)
            # Treat review error as a failure to pass, mark with error note
            error_note = f"[Review Error: {str(e)}] - Original Output:\n{code}"
            return {"completed": {task_content: error_note}}
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(
                "💥 Unexpected error in reviewer for task %d after %.2f seconds: %s",
                task_index + 1,
                elapsed_time,
                e,
                exc_info=True,
            )
            error_note = f"[Unexpected Review Error] - Original Output:\n{code}"
            return {"completed": {task_content: error_note}}


# --- End of Sequential Execution Logic ---
async def collect(state: State) -> dict[str, str]:
    """
    Aggregate all completed task outputs when done.
    """
    completed_count = len(state["completed"])
    total_tasks = len(state.get("tasks", []))  # Use .get in case 'tasks' key is missing
    logger.info(
        "📦 Collecting results: %d/%d tasks completed", completed_count, total_tasks
    )

    if completed_count > 0:  # Allow collecting even if not all planned tasks succeeded
        final_parts = []
        # Try to preserve task order from the original plan if possible
        task_order = state.get("tasks", [])
        if task_order:
            for task in task_order:
                if task in state["completed"]:
                    final_parts.append(f"### {task}\n\n{state['completed'][task]}")
                # Optionally add note for tasks that were planned but not completed?
                # elif task in state.get("results", {}): # If it was processed but not reviewed/pass
                #     final_parts.append(f"### {task}\n\n[Task processed but not accepted]\n{state['results'][task]}")
        else:
            # Fallback if task order is lost
            final_parts = [f"### {t}\n\n{c}" for t, c in state["completed"].items()]

        final = "\n\n".join(final_parts)
        logger.info("🎉 Final result aggregated: %d chars", len(final))
        log_context_size(logger, final, "Aggregated final result")
        memory.add([{"role": "assistant", "content": final}], user_id="workflow")
        return {"final_result": final}
    else:
        logger.info("📭 No tasks were successfully completed to collect")
        return {"final_result": "No tasks were completed successfully."}


# ------------------------------------------------------------------
# 7. Build and compile the graph (Updated for sequential execution and task history)
# ------------------------------------------------------------------
def create_workflow_graph():
    """Factory function to create the graph."""
    workflow_graph = StateGraph(State)

    # Entry point
    workflow_graph.add_node("router", router)

    # Chat path
    workflow_graph.add_node("chat", chat)

    # Coding paths (need_context and heavy both lead to full planning)
    workflow_graph.add_node("refresh_static", refresh_static)
    workflow_graph.add_node("context_provider", context_provider)
    workflow_graph.add_node(
        "plan", plan
    )  # Now initializes current_task_index and task_histories

    # Sequential task processing nodes
    workflow_graph.add_node("process_task", process_task)  # Prepares task prompt
    workflow_graph.add_node("worker", worker)  # Executes task (uses history)
    workflow_graph.add_node("review", review)  # Reviews output (stores history)
    workflow_graph.add_node("collect", collect)  # Aggregates results

    # Routing logic
    workflow_graph.add_conditional_edges(
        "router",
        lambda s: s["route"],
        {
            "chat": "chat",
            "need_context": "refresh_static",
            "heavy": "refresh_static",
            "default": "plan",  # Direct path for default
        },
    )

    # Core flows
    workflow_graph.add_edge(START, "router")
    workflow_graph.add_edge("refresh_static", "context_provider")
    workflow_graph.add_edge("context_provider", "plan")

    # Sequential task execution flow
    # After planning, decide if there are tasks to process
    workflow_graph.add_conditional_edges(
        "plan", route_to_worker_or_end, ["process_task", "collect"]
    )
    # Process task -> Worker -> Review
    workflow_graph.add_edge("process_task", "worker")
    workflow_graph.add_edge("worker", "review")
    # After review, decide again if there are more tasks or if we collect
    workflow_graph.add_conditional_edges(
        "review", route_to_worker_or_end, ["process_task", "collect"]
    )

    # Collect results and end
    workflow_graph.add_edge("collect", END)

    # Chat path ends directly
    workflow_graph.add_edge("chat", END)

    return workflow_graph


# Create and compile the graph with a higher recursion limit for complex retries
graph = create_workflow_graph().compile()  # Increased from default 25


# ------------------------------------------------------------------
# 8. Public API entrypoint (Enhanced logging)
# ------------------------------------------------------------------
async def run_agent(prompt: str) -> str:
    """
    Run the full workflow and return the final aggregated result.
    """
    logger.info("🚀 Starting workflow execution")
    logger.info(
        "📝 User prompt: %s", prompt[:100] + "..." if len(prompt) > 100 else prompt
    )
    log_context_size(logger, prompt, "Initial user prompt")

    # Initial memory store
    memory.add([{"role": "user", "content": prompt}], user_id="workflow")

    start_time = time.time()
    initial_state: State = {
        "prompt": prompt,
        "static_ctx": await build_static_snapshot(),  # Build initial snapshot
        "dynamic_ctx": "",
        "tasks": [],
        "current_task_index": 0,  # Initialize task index
        "results": {},
        "completed": {},
        "final_result": "",
        "route": "default",  # Default route
        "task_histories": {},  # Initialize task history
    }
    # Log initial context size
    log_context_size(logger, initial_state["static_ctx"], "Initial static context")
    logger.debug("🔧 Initial state prepared")

    try:
        out = await graph.ainvoke(initial_state, config={"recursion_limit": 5})
        elapsed_time = time.time() - start_time
        result = out.get(
            "final_result", "Workflow completed, but no final result was generated."
        )
        logger.info(
            "🏁 Workflow completed in %.2f seconds, result: %d chars",
            elapsed_time,
            len(result),
        )
        log_context_size(logger, result, "Final workflow result")
        return result
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(
            "💥 Workflow failed after %.2f seconds: %s", elapsed_time, e, exc_info=True
        )
        return f"An error occurred during workflow execution: {str(e)}"


# ------------------------------------------------------------------
# 9. Graph visualization (for dev)
# ------------------------------------------------------------------
if __name__ == "__main__":
    # Set logging level to DEBUG for development
    logger.setLevel(logging.DEBUG)
    print("=== Mermaid Diagram ===")
    try:
        mermaid_diagram = graph.get_graph().draw_mermaid()
        print(mermaid_diagram)
        # Optionally save to file
        # Path("workflow_graph_sequential.mmd").write_text(mermaid_diagram)
        # print("✅ workflow_graph_sequential.mmd generated")
    except Exception as e:
        print(f"⚠ Mermaid diagram generation failed: {e}")

    try:
        png_data = graph.get_graph().draw_mermaid_png()
        Path("workflow_graph_sequential.png").write_bytes(png_data)
        print("✅ workflow_graph_sequential.png generated")
    except Exception as e:
        print(f"⚠ PNG generation failed (install pyppeteer for support): {e}")
