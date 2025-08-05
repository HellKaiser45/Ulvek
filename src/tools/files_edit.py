# filetool.py  –  JSON-safe file tools for Pydantic-AI agents
from __future__ import annotations

import difflib
import inspect
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel


# ---------- Custom Exception --------------------------------------------------
class UserRejectedException(Exception):
    """Raised when a user rejects a proposed file change."""

    def __init__(
        self, message: str, feedback: str = "", file_path: Optional[str] = None
    ):
        super().__init__(message)
        self.feedback = feedback
        self.file_path = file_path


# ---------- Parameter models (JSON-safe) ------------------------------------
class WriteParams(BaseModel):
    file_path: str
    """Absolute or relative path to the file that should be written."""
    content: str
    """Text that will replace the entire content of the file."""


class EditParams(BaseModel):
    file_path: str
    """Absolute or relative path to the file that should be modified."""
    old: str = ""
    """Substring that will be searched for and replaced. Empty string edits at file start."""
    new: str = ""
    """Replacement text."""
    expect: int = 1
    """Number of expected `old` substring occurrences; mismatch raises an error."""


# ---------- Helpers ----------------------------------------------------------
def _log(**ctx) -> None:
    frame = inspect.currentframe()
    try:
        caller = frame.f_back.f_code.co_name  # type: ignore
    finally:
        del frame
    kv = " ".join(f"{k}={v!r}" for k, v in ctx.items())
    print(f"[filetool.{caller}] {kv}")


def _ask_user_feedback(diff: List[str]) -> tuple[bool, str]:
    """Ask user for confirmation and collect feedback if rejected.

    Returns:
        tuple: (accepted: bool, feedback: str)
        feedback is empty string if accepted, contains user feedback if rejected
    """
    if not diff:
        return False, "No changes detected"

    print("\n".join(diff))

    while True:
        try:
            choice = input("Apply this change? [y/N/q - to quit] ").strip().lower()
            if choice == "q":
                print("Quitting.")
                sys.exit(0)

            if choice in {"y", "yes"}:
                return True, ""

            if choice in {"", "n", "no"}:
                # Collect feedback when user rejects
                feedback = input(
                    "❌ Edit rejected. Please provide feedback (or press Enter for none): "
                ).strip()
                return False, feedback

            # Handle other responses as rejection with feedback
            feedback = choice if choice else "User rejected without feedback"
            return False, feedback

        except (KeyboardInterrupt, EOFError):
            print("\nAborted by user.")
            return False, "User interrupted the process"


def _ensure_in_workspace(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise ValueError(f"Path must be inside workspace {Path.cwd()}")


def _diff(name: str, old: str, new: str) -> List[str]:
    return list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
            lineterm="",
        )
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# ---------- Core logic -------------------------------------------------------
async def _write_core(p: Path, content: str) -> List[str]:
    _log(file=str(p))
    _ensure_in_workspace(p)

    original = _read(p)
    diff = _diff(p.name, original, content)
    return diff


async def _edit_core(p: Path, old: str, new: str, expect: int) -> List[str]:
    _log(file=str(p), old=old, new=new, expect=expect)
    _ensure_in_workspace(p)

    original = _read(p)
    if not original and old:
        raise ValueError("Cannot edit non-existent file with non-empty old string")

    count = original.count(old)
    if count == 0:
        raise ValueError("old string not found")
    if count != expect:
        raise ValueError(f"expected {expect} occurrences, found {count}")

    corrected = original.replace(old, new)
    diff = _diff(p.name, original, corrected)
    return diff


async def _commit(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp.write(text)
        tmp.flush()
        tmp_path = Path(tmp.name)
    try:
        if path.exists():
            os.chmod(tmp_path, path.stat().st_mode)
        tmp_path.replace(path)
        _log(status="committed", file=str(path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ---------- Pydantic-AI tools ------------------------------------------------
# ---------- Pydantic-AI tools ------------------------------------------------
async def write_file(params: WriteParams) -> List[str]:
    """
    Create or overwrite a file after presenting a diff to the user for confirmation.

    This tool calculates the difference between the current file content (if any)
    and the proposed new `content`. It then displays this diff to the user and
    waits for explicit confirmation ("y" or "yes"). If the user confirms, the
    file is written. If the user rejects ("n", "no", or any other input), or if
    the user provides feedback during rejection, a `UserRejectedException` is raised.
    This exception contains the user's feedback, allowing the calling agent to
    potentially refine its approach.

    Args:
        params (WriteParams): An object containing:
            - `file_path` (str): The path to the file.
            - `content` (str): The new content for the file.

    Returns:
        List[str]: A list of strings representing the unified diff of the
                   changes that were applied.

    Raises:
        UserRejectedException: If the user does not confirm the change. The
                               exception object includes the `feedback` provided
                               by the user and the `file_path`.
        ValueError: If the path is outside the allowed workspace.
        IOError: If there is an error reading the existing file or writing the
                 new one.
    """
    path = Path(params.file_path).resolve()
    diff = await _write_core(path, params.content)
    approved, feedback = _ask_user_feedback(diff)
    if approved:
        await _commit(path, params.content)
        _log(status="applied", file=str(path))
    else:
        _log(status="rejected", file=str(path), feedback=feedback)
        raise UserRejectedException(
            f"User rejected changes to {params.file_path}",
            feedback=feedback,
            file_path=params.file_path,
        )
    return diff


async def edit_file(params: EditParams) -> List[str]:
    """
    Replace text within an existing file after presenting a diff for confirmation.

    This tool searches for the `old` substring within the specified file. If found
    exactly `expect` times, it calculates the diff for replacing it with the `new`
    substring. The diff is shown to the user for confirmation ("y" or "yes").
    If confirmed, the change is applied. If the user rejects the change or provides
    feedback, a `UserRejectedException` is raised, containing the feedback for
    the agent to use.

    Args:
        params (EditParams): An object containing:
            - `file_path` (str): The path to the file.
            - `old` (str): The substring to be replaced. An empty string implies
                           inserting `new` at the beginning of the file.
            - `new` (str): The replacement text.
            - `expect` (int, optional): The expected number of occurrences of
                                        `old`. Defaults to 1. If the actual
                                        count differs, an error is raised before
                                        user confirmation.

    Returns:
        List[str]: A list of strings representing the unified diff of the
                   changes that were applied.

    Raises:
        UserRejectedException: If the user does not confirm the change. The
                               exception object includes the `feedback` provided
                               by the user and the `file_path`.
        ValueError: If the path is outside the allowed workspace, if `old` is
                    specified but the file doesn't exist, if `old` is not found
                    the expected number of times, or if `old` is not found at all.
        IOError: If there is an error reading the file or writing the changes.
    """
    path = Path(params.file_path).resolve()
    diff = await _edit_core(path, params.old, params.new, params.expect)
    approved, feedback = _ask_user_feedback(diff)
    if approved:
        original = _read(path)
        corrected = original.replace(params.old, params.new)
        await _commit(path, corrected)
        _log(status="applied", file=str(path))
    else:
        _log(status="rejected", file=str(path), feedback=feedback)
        raise UserRejectedException(
            f"User rejected changes to {params.file_path}",
            feedback=feedback,
            file_path=params.file_path,
        )
    return diff


# ---------- Batch Edit (Updated to handle exceptions) ------------------------
class BatchEditItem(BaseModel):
    file_path: str
    """Absolute or relative path to the file that should be modified."""
    old: str
    """Substring that will be searched for and replaced."""
    new: str
    """Replacement text."""
    expect: int = 1
    """Number of expected `old` substring occurrences; mismatch raises an error."""


class BatchEditParams(BaseModel):
    edits: List[BatchEditItem]


async def batch_edit(params: BatchEditParams) -> List[List[str]]:
    """Apply several edits atomically; returns one diff per file.

    Note: This implementation applies edits sequentially.
    If any edit is rejected, a UserRejectedException is raised and
    subsequent edits are not attempted. For true atomicity, a more complex
    transactional system would be needed (e.g., applying all diffs to
    temporary files first, then committing all).
    """
    diffs = []
    for item in params.edits:
        try:
            diff = await edit_file(
                EditParams(
                    file_path=item.file_path,
                    old=item.old,
                    new=item.new,
                    expect=item.expect,
                )
            )
            diffs.append(diff)
        except UserRejectedException:
            # Re-raise immediately, stopping the batch
            raise
    return diffs
