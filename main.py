from src.tools.prompt_eval import predictor
import asyncio
from src.agents.agent import context_retriever_agent
from src.tools.codebase import get_non_ignored_files, process_file
from src.tools.search_files import search_files
from pydantic_ai import Agent  # only for type checking
from pydantic_ai.messages import (
    ToolCallPart,
    ToolReturnPart,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
)
from pprint import pprint
import csv
from typing import Any, Dict, List


# ------------------------------------------------------------------
# Helper: flatten nested dicts/lists so we can write a plain table.
# ------------------------------------------------------------------
def flatten_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turns {'task_type_1': ['Open QA'], 'task_type_prob': [0.322], ...}
    into {'task_type_1': 'Open QA', 'task_type_prob': 0.322, ...}
    by taking the *first* item out of any list/tuple.
    """
    flat = {}
    for k, v in analysis.items():
        flat[k] = v[0] if isinstance(v, (list, tuple)) and len(v) == 1 else v
    return flat


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
async def main() -> None:
    records: List[Dict[str, Any]] = []

    while True:
        raw = input("\n🤖 Enter your prompt (or q/quit to exit):\n> ").strip()
        if raw.lower() in {"q", "quit", ""}:
            break

        # Run the analysis
        analysis = (
            await predictor(raw)
            if asyncio.iscoroutine(predictor(raw))
            else predictor(raw)
        )

        # Store prompt + flattened analysis
        flat = flatten_analysis(analysis)
        flat["prompt"] = raw
        records.append(flat)

    # ------------------------------------------------------------------
    # Write CSV on exit
    # ------------------------------------------------------------------
    if records:
        fieldnames = ["prompt"] + [k for k in records[0] if k != "prompt"]
        with open("prompts_analysis.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
        print(f"\n✅ CSV saved: prompts_analysis.csv ({len(records)} rows)")
    else:
        print("\nℹ️  No data to save.")


if __name__ == "__main__":
    asyncio.run(main())
