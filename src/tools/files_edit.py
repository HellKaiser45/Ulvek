# filetool.py
# Stand-alone Python 3.12+ module
# Provides WriteRequest / EditRequest -> atomic file operations
# Zero external deps beyond stdlib

from __future__ import annotations

import asyncio
import difflib
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, NewType, Protocol, TypedDict, Union

# ------------- Domain Primitives ---------------------------------------------
AbsolutePath = NewType("AbsolutePath", Path)
Content = NewType("Content", str)


class FileOperation(Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    NOOP = "NOOP"


class ValidationError(TypedDict):
    message: str
    field: str | None


# ------------- Requests ------------------------------------------------------
@dataclass(slots=True)
class WriteRequest:
    file_path: AbsolutePath
    content: Content


@dataclass(slots=True)
class EditRequest:
    file_path: AbsolutePath
    old: str
    new: str
    expect: int = 1


Request = Union[WriteRequest, EditRequest]


# ------------- Plan ----------------------------------------------------------
@dataclass(slots=True)
class Plan:
    original: Content
    corrected: Content
    kind: FileOperation
    diff_lines: List[str]


# ------------- Validation ----------------------------------------------------
def validate_path(p: AbsolutePath, workspace_root: Path) -> ValidationError | None:
    try:
        resolved = p.resolve()
    except Exception as exc:
        return ValidationError(message=str(exc), field="file_path")
    if not resolved.is_relative_to(workspace_root.resolve()):
        return ValidationError(
            message=f"Path must be inside workspace {workspace_root}", field="file_path"
        )
    return None


def validate_content(c: Content) -> ValidationError | None:
    try:
        c.encode("utf-8")
    except UnicodeError as exc:
        return ValidationError(message=str(exc), field="content")
    return None


# ------------- Content Corrector --------------------------------------------
class ContentCorrector(Protocol):
    async def correct(self, original: Content, proposed: Content) -> Content: ...


class IdentityCorrector:
    async def correct(self, original: Content, proposed: Content) -> Content:
        return proposed


# ------------- Diff Renderer -------------------------------------------------
def render_diff(name: str, old: Content, new: Content) -> List[str]:
    return list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
            lineterm="",
        )
    )


# ------------- Core Pipeline -------------------------------------------------
async def _read_or_empty(p: AbsolutePath) -> Content:
    try:
        return Content(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Content("")


async def _build_write_plan(
    req: WriteRequest, workspace: Path, corrector: ContentCorrector
) -> Plan:
    original = await _read_or_empty(req.file_path)
    corrected = await corrector.correct(original, req.content)
    kind = FileOperation.UPDATE if original else FileOperation.CREATE
    if original == corrected:
        kind = FileOperation.NOOP
    diff_lines = render_diff(req.file_path.name, original, corrected)
    return Plan(original, corrected, kind, diff_lines)


async def _build_edit_plan(
    req: EditRequest, workspace: Path, corrector: ContentCorrector
) -> Plan:
    original = await _read_or_empty(req.file_path)

    # 1.  Decide whether we are creating or editing
    if not original and not req.old:  # create new file
        corrected = await corrector.correct(original, Content(req.new))
        kind = FileOperation.CREATE
    elif not original and req.old:  # edit non-existent file
        raise ValueError("Cannot edit non-existent file with non-empty old string")
    else:  # normal edit
        count = original.count(req.old)
        if count == 0:
            raise ValueError("old string not found")
        if count != req.expect:
            raise ValueError(f"expected {req.expect} occurrences, found {count}")
        corrected_raw = original.replace(req.old, req.new)
        corrected = await corrector.correct(original, Content(corrected_raw))
        kind = FileOperation.UPDATE if original != corrected else FileOperation.NOOP

    diff_lines = render_diff(req.file_path.name, original, corrected)
    return Plan(original, corrected, kind, diff_lines)


async def build_plan(
    req: Request, workspace: Path, corrector: ContentCorrector | None = None
) -> Plan:
    if (err := validate_path(req.file_path, workspace)) is not None:
        raise ValueError(err["message"])
    if isinstance(req, WriteRequest) and (err := validate_content(req.content)):
        raise ValueError(err["message"])

    c = corrector or IdentityCorrector()
    if isinstance(req, WriteRequest):
        return await _build_write_plan(req, workspace, c)
    return await _build_edit_plan(req, workspace, c)


async def commit_plan(plan: Plan) -> None:
    if plan.kind == FileOperation.NOOP:
        return
    p = Path(plan.corrected)  # just to extract parent
    p = Path(p)  # type: ignore
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=p.parent, delete=False
    ) as tmp:
        tmp.write(plan.corrected)
        tmp.flush()
        tmp_path = Path(tmp.name)
    try:
        original_path = Path(plan.original)  # type: ignore
        if original_path.exists():
            stat = original_path.stat()
            os.chmod(tmp_path, stat.st_mode)
        tmp_path.replace(p)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ------------- Public API ----------------------------------------------------
async def write_file(
    req: WriteRequest, workspace: Path, corrector: ContentCorrector | None = None
) -> Plan:
    plan = await build_plan(req, workspace, corrector)
    await commit_plan(plan)
    return plan


async def edit_file(
    req: EditRequest, workspace: Path, corrector: ContentCorrector | None = None
) -> Plan:
    plan = await build_plan(req, workspace, corrector)
    await commit_plan(plan)
    return plan


# ------------------ Tools for agents --------------------------------


async def fs_write(file_path: str, content: str) -> list[str]:
    """Propose creating/overwriting a file relative to CWD."""
    req = WriteRequest(
        file_path=AbsolutePath(Path(file_path).resolve()),
        content=Content(content),
    )
    plan = await build_plan(req, Path.cwd())
    return plan.diff_lines


async def fs_edit(
    file_path: str,
    old_string: str,
    new_string: str,
    expected_replacements: int = 1,
) -> list[str]:
    """Propose editing a file relative to CWD."""
    req = EditRequest(
        file_path=AbsolutePath(Path(file_path).resolve()),
        old=old_string,
        new=new_string,
        expect=expected_replacements,
    )
    plan = await build_plan(req, Path.cwd())
    return plan.diff_lines
