# Workflow Module

This folder contains one self-contained LangGraph workflow that routes any user prompt to the correct Pydantic-AI agent and persists memory across turns.

## 📁 Files

| File     | Purpose |
|----------|---------|
| `graph.py`  | Declares the shared State, builds the LangGraph, and exports a ready-to-use graph instance. |
| `runner.py` | Thin async helper that injects prompt, route, and memory into the graph and returns the final answer. |

## 🧭 How it works (30-second tour)

1. **State** is a TypedDict that every node reads/writes.
2. One supervisor node (`classify`) decides the route.
3. Four worker nodes (`CHAT`, `CODE_SNIPPET`, `CODE_NEEDS_CONTEXT`, `CODE_ORCHESTRATE`) wrap your existing Pydantic-AI agents.
4. Memory (mem0) is queried before the graph runs and the interaction is stored after it finishes.

## 🚀 Quick start

```bash
python -m src.workflow.runner   # or import run_user_turn elsewhere
```

## 📚 External documentation

- **LangGraph concepts**: https://langchain-ai.github.io/langgraph/tutorials/workflows/
- **LangGraph 101 for beginners**: https://medium.com/@vamshiginna1606/langgraph-101-build-your-first-agentic-ai-workflow-step-by-step-for-beginners-b9a1a0cec59a
- **Parallel / Orchestrator patterns**: https://surma.dev/things/langgraph/

## 🛠️ Evolve & maintain

| Task | Where to change |
|------|-----------------|
| **Add a new agent** | Drop the agent into `src/agents/agent.py`, then add one line in `graph.py` → `NODE_MAP["NEW_KEY"] = make_node(new_agent)`. No graph rebuild needed. |
| **Change routing logic** | Replace the hard-coded `"CODE_SNIPPET"` in `runner.py` with your own classifier function. |
| **Add streaming** | Switch `graph.ainvoke(...)` to `graph.astream(...)` in `runner.py`. |
| **Human-in-the-loop** | Add `interrupt_before=["classify"]` when compiling the graph (see LangGraph docs). |
| **Persistent memory tuning** | Edit config dict in `src/config.py`; the same object is reused by Memory.from_config. |

## 🧪 Testing tips

- `pytest src/workflow/test_runner.py` – create a tiny test file that calls `run_user_turn("write fibonacci")`.
- `graph.get_graph().draw_mermaid_png()` – save the PNG to see the DAG visually.