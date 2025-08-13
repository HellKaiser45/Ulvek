# filetool.py  –  JSON-safe file tools for Pydantic-AI agents
from __future__ import annotations

import difflib
import pathlib
import textwrap
import json
from pathlib import Path
from pydantic import BaseModel, Field
from src.app.agents.schemas import AgentDeps
from pydantic_ai import RunContext
from src.app.utils.frontends_adapters.interaction_manager import (
    emit_text_message_start,
    emit_text_message_content,
    emit_text_message_end,
    encode_event,
    send_event,
    EVENTS_QUEUE,
)


# ---------- Parameter models (JSON-safe) ------------------------------------
class WriteParams(BaseModel):
    file_path: str = Field(
        ...,
        description="File to create or overwrite (relative to workspace root).",
        examples=["src/main.py", "README.md"],
    )
    content: str = Field(
        ...,
        description="Complete new file content.",
    )


class EditParams(BaseModel):
    file_path: str = Field(
        ...,
        description="File to patch (relative to workspace root).",
        examples=["src/utils.py"],
    )
    old: str = Field(
        ...,
        description="Exact code block to find and remove.",
    )
    new: str = Field(
        ...,
        description="Code block to insert in its place.",
    )
    expect: int = Field(
        1,
        description="How many occurrences of `old` must exist (safety check).",
    )


# ---------- Helpers ----------------------------------------------------------


def _ensure_in_workspace(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise ValueError(f"Path must be inside workspace {Path.cwd()}")


async def _ask_user_feedback(
    run_id: str,
    diff_lines: list[str],
) -> tuple[bool, str]:
    """
    Ask the user via AG-UI for confirmation and optional feedback.
    Returns (accepted, feedback).
    """
    diff_text = "\n".join(diff_lines)

    # 1. Show the diff
    start_ev, msg_id = emit_text_message_start()
    await send_event(run_id, encode_event(start_ev))
    content_ev = emit_text_message_content(msg_id, f"Proposed diff:\n{diff_text}")
    await send_event(run_id, encode_event(content_ev))
    end_ev = emit_text_message_end(msg_id)
    await send_event(run_id, encode_event(end_ev))

    # 2. Ask yes/no
    request_payload = json.dumps(
        {
            "type": "custom",
            "name": "requestInput",
            "value": {"prompt": "Apply this change? [y/n] ", "kind": "confirm"},
        }
    )
    await send_event(run_id, request_payload)

    # 3. Wait for answer (same loop as before)
    while True:
        rid, raw = await EVENTS_QUEUE.get()
        if rid != run_id:
            continue
        data = json.loads(raw)
        if data.get("type") == "custom" and data.get("name") == "userInput":
            choice = str(data.get("value", {}).get("text", "")).strip().lower()
            if choice in {"y", "yes", "true", "1"}:
                return True, ""

            # rejected → ask for feedback
            fb_payload = json.dumps(
                {
                    "type": "custom",
                    "name": "requestInput",
                    "value": {
                        "prompt": "❌ Edit rejected. Feedback (Enter for none): ",
                        "kind": "input",
                    },
                }
            )
            await send_event(run_id, fb_payload)

            while True:
                rid2, raw2 = await EVENTS_QUEUE.get()
                if rid2 != run_id:
                    continue
                data2 = json.loads(raw2)
                if data2.get("type") == "custom" and data2.get("name") == "userInput":
                    return False, str(data2.get("value", {}).get("text", ""))


# ---------- Pydantic-AI tools ------------------------------------------------
async def write_file(ctx: RunContext[AgentDeps], params: WriteParams) -> str:
    """
    Create or overwrite an entire file.

    1. Shows a unified diff preview.
    2. Asks the user for confirmation.
    3. Writes atomically only if accepted.

    Returns
    -------
    str
        Success or cancellation message.
    """
    src = pathlib.Path(params.file_path)
    try:
        _ensure_in_workspace(src)
    except ValueError as e:
        return str(e)

    exists = src.exists()
    original = src.read_text() if exists else ""
    new_content = textwrap.dedent(params.content).lstrip()

    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True) or [""],
            new_content.splitlines(keepends=True),
            fromfile=str(src) if exists else "/dev/null",
            tofile=str(src),
            lineterm="",
        )
    )

    accepted, feedback = await _ask_user_feedback(ctx.deps.run_id, diff_lines)
    if not accepted:
        return (
            f"Write cancelled. Feedback: {feedback}" if feedback else "Write cancelled."
        )

    tmp = src.with_suffix(src.suffix + ".tmp")
    tmp.write_text(new_content)
    tmp.replace(src)
    return f"{'Overwrote' if exists else 'Created'} {params.file_path}"


async def edit_file(ctx: RunContext[AgentDeps], params: EditParams) -> str:
    """
    Create or overwrite an entire file.

    1. Shows a unified diff preview.
    2. Asks the user for confirmation.
    3. Writes atomically only if accepted.

    Returns
    -------
    str
        Success or cancellation message.
    """
    src = pathlib.Path(params.file_path)
    try:
        _ensure_in_workspace(src)
    except ValueError as e:
        return str(e)

    if not src.exists():
        return f"File not found: {params.file_path}"

    original = src.read_text()
    search = textwrap.dedent(params.old).strip()

    # locate fragment
    if not search:
        start, end = 0, 0
    else:
        start = original.find(search)
        if start == -1:
            sm = difflib.SequenceMatcher(
                None, original.splitlines(), params.old.splitlines()
            )
            if sm.ratio() < 0.95:
                return f"Fragment not found or ambiguous in {params.file_path}"
            mb = sm.get_matching_blocks()[0]
            lines = original.splitlines(keepends=True)
            start = sum(len(lines[i]) for i in range(mb.a))
            end = start + len("".join(lines[mb.a : mb.a + mb.size]))
        else:
            end = start + len(search)

    new_content = (
        original[:start] + textwrap.dedent(params.new).lstrip() + original[end:]
    )
    if new_content == original:
        return "No change applied (identical)."

    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=str(src),
            tofile=str(src),
            lineterm="",
        )
    )

    accepted, feedback = await _ask_user_feedback(ctx.deps.run_id, diff_lines)
    if not accepted:
        return (
            f"Edit cancelled. Feedback: {feedback}" if feedback else "Edit cancelled."
        )

    tmp = src.with_suffix(src.suffix + ".tmp")
    tmp.write_text(new_content)
    tmp.replace(src)
    return f"Successfully applied edit to {params.file_path}"
