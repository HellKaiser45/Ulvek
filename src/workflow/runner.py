# src/workflow/runner.py
from src.workflow.graph import graph, State
from src.tools.memory import m as memory


async def run_user_turn(prompt: str, *, user_id: str = "default") -> str:
    """Run one turn through the LangGraph workflow."""
    memories = memory.search(prompt, user_id=user_id)

    # Build a *complete* State dict (no extra keys)
    state: State = {
        "prompt": prompt,
        "route": "CODE_SNIPPET",  # plug classifier here later
        "context": {"memories": memories},
        "result": None,
        "messages": [],
    }

    final = await graph.ainvoke(state)
    result = final.get("result", "")

    # persist interaction
    memory.add({"role": "user", "content": prompt}, user_id=user_id)
    memory.add({"role": "assistant", "content": result}, user_id=user_id)

    return result
