from __future__ import annotations

import operator
from typing import Annotated, TypedDict, Literal
from langgraph.graph import START, END, StateGraph
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


# ------------------------------------------------------------------
# 1. Unified state
# ------------------------------------------------------------------
class State(TypedDict):
    prompt: str
    static_ctx: str
    dynamic_ctx: str
    tasks: Annotated[list[str], operator.add]
    index: int
    completed: dict[str, str]
    final: str
    route: Literal["chat", "need_context", "heavy", "default"]
    candidate: str


# ------------------------------------------------------------------
# 2. Utility: static snapshot
# ------------------------------------------------------------------
async def build_static() -> str:
    files = await get_non_ignored_files()
    desc = await process_file(files)
    return "\n".join(f"- {f.file_path}: {f.description}" for f in desc)


# ------------------------------------------------------------------
# 3. Core nodes
# ------------------------------------------------------------------
async def router(state: State) -> dict[str, str]:
    e = predictor(state["prompt"])
    if e["task_type_prob"][0] > 0.9 and e["reasoning"][0] < 0.01:
        return {"route": "chat"}
    if e["contextual_knowledge"][0] > 0.5:
        return {"route": "need_context"}
    if e["reasoning"][0] > 0.2:
        return {"route": "heavy"}
    return {"route": "default"}


async def chat(state: State) -> dict[str, str]:
    resp = await conversational_agent.run(state["prompt"])
    memory.add([{"role": "assistant", "content": resp.output}], user_id="workflow")
    return {"final": resp.output}


async def refresh_static(state: State) -> dict[str, str]:
    return {"static_ctx": await build_static()}


async def context_node(state: State) -> dict[str, str]:
    out = await context_retriever_agent.run(f"{state['static_ctx']}\n{state['prompt']}")
    return {"dynamic_ctx": out.output}


async def plan(state: State) -> dict[str, object]:
    prompt = f"{state['static_ctx']}\n{state['dynamic_ctx']}\n{state['prompt']}"
    tasks = (await orchestrator_agent.run(prompt)).output.tasks
    return {"tasks": tasks, "index": 0, "completed": {}}


async def worker(state: State) -> dict[str, str]:
    task = state["tasks"][state["index"]]
    prompt = f"{state['static_ctx']}\n{state['dynamic_ctx']}\nTask: {task}"
    code = (await coding_agent.run(prompt)).output
    return {"candidate": code}


async def review(state: State) -> dict[str, object]:
    task = state["tasks"][state["index"]]
    review = await evaluator_agent.run(f"Task: {task}\n{state['candidate']}")
    if review.output.grade == "pass":
        memory.add(
            [{"role": "assistant", "content": f"{task}: {state['candidate']}"}],
            user_id="workflow",
        )
        state["completed"][task] = state["candidate"]
        return {"index": state["index"] + 1}
    state["dynamic_ctx"] = f"Feedback: {review.output.feedback}"
    return {}  # Retry immediately


async def collect(state: State) -> dict[str, str]:
    final = "\n\n".join(f"{t}: {c}" for t, c in state["completed"].items())
    memory.add([{"role": "assistant", "content": final}], user_id="workflow")
    return {"final": final}


# ------------------------------------------------------------------
# 4. Graph construction
# ------------------------------------------------------------------
graph = (
    StateGraph(State)
    .add_node("router", router)
    .add_node("chat", chat)
    .add_node("refresh_static", refresh_static)
    .add_node("context", context_node)
    .add_node("plan", plan)
    .add_node("worker", worker)
    .add_node("review", review)
    .add_node("collect", collect)
    .add_edge(START, "router")
    .add_conditional_edges(
        "router",
        lambda s: s["route"],
        {
            "chat": "chat",
            "need_context": "refresh_static",
            "heavy": "refresh_static",
            "default": "plan",
        },
    )
    .add_edge("refresh_static", "context")
    .add_edge("context", "plan")
    .add_edge("plan", "worker")
    .add_edge("worker", "review")
    .add_conditional_edges(
        "review",
        lambda s: "worker" if s["index"] < len(s["tasks"]) else "collect",
        ["worker", "collect"],
    )
    .add_edge("collect", END)
    .compile()
)


# ------------------------------------------------------------------
# 5. Public API
# ------------------------------------------------------------------
async def run_agent(prompt: str) -> str:
    memory.add([{"role": "user", "content": prompt}], user_id="workflow")
    initial: State = {
        "prompt": prompt,
        "static_ctx": await build_static(),
        "dynamic_ctx": "",
        "tasks": [],
        "index": 0,
        "completed": {},
        "final": "",
        "route": "default",
        "candidate": "",
    }
    out = await graph.ainvoke(initial)
    return out["final"]


""
