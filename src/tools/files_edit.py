# filetool.py
# Stand-alone Python 3.12+ module
# Provides WriteRequest / EditRequest -> atomic file operations
# Zero external deps beyond stdlib

from __future__ import annotations

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
    """Enumeration of possible file operations."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    NOOP = "NOOP"


class ValidationError(TypedDict):
    """Type definition for validation error messages."""
    message: str
    field: str | None


# ------------- Requests ------------------------------------------------------
@dataclass(slots=True)
class WriteRequest:
    """Request to write or overwrite a file with new content."""
    file_path: AbsolutePath
    content: Content


@dataclass(slots=True)
class EditRequest:
    """Request to edit a file by replacing old content with new content."""
    file_path: AbsolutePath
    old: str
    new: str
    expect: int = 1


Request = Union[WriteRequest, EditRequest]


# ------------- Plan ----------------------------------------------------------
@dataclass(slots=True)
class Plan:
    """Execution plan for a file operation containing original and corrected content."""
    original: Content
    corrected: Content
    kind: FileOperation
    diff_lines: List[str]


# ------------- Validation ----------------------------------------------------
def validate_path(p: AbsolutePath, workspace_root: Path) -> ValidationError | None:
    """
    Validate that a file path is within the workspace root directory.
    
    Args:
        p: The absolute path to validate
        workspace_root: The root directory of the workspace
        
    Returns:
        ValidationError if path is invalid, None otherwise
    """
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
    """
    Validate that content can be encoded as UTF-8.
    
    Args:
        c: The content to validate
        
    Returns:
        ValidationError if content is invalid, None otherwise
    """
    try:
        c.encode("utf-8")
    except UnicodeError as exc:
        return ValidationError(message=str(exc), field="content")
    return None


# ------------- Content Corrector --------------------------------------------
class ContentCorrector(Protocol):
    """Protocol for content correction implementations."""
    async def correct(self, original: Content, proposed: Content) -> Content: ...


class IdentityCorrector:
    """Content corrector that returns proposed content unchanged."""
    async def correct(self, original: Content, proposed: Content) -> Content:
        """Return the proposed content without any modifications."""
        return proposed


# ------------- Diff Renderer -------------------------------------------------
def render_diff(name: str, old: Content, new: Content) -> List[str]:
    """
    Generate a unified diff between old and new content.
    
    Args:
        name: Name of the file being diffed
        old: Original content
        new: New content
        
    Returns:
        List of diff lines
    """
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
    """
    Read file content or return empty string if file doesn't exist.
    
    Args:
        p: Path to the file to read
        
    Returns:
        File content as string, or empty string if file doesn't exist
    """
    try:
        return Content(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Content("")


async def _build_write_plan(
    req: WriteRequest, workspace: Path, corrector: ContentCorrector
) -> Plan:
    """
    Build a plan for writing or overwriting a file.
    
    Args:
        req: The write request
        workspace: Workspace root directory
        corrector: Content corrector to apply
        
    Returns:
        Plan containing the operation details
    """
    original = await _read_or_empty(req.file_path)
    corrected = await corrector.correct(original, req.content)
    kind = FileOperation.UPDATE if original else FileOperation.CREATE
    if original == corrected:
        kind = FileOperation.NOOP
    diff_lines = render_diff(req.file_path.name, original, corrected)
    print(f"[_build_write_plan] kind={kind} file={req.file_path}")
    return Plan(original, corrected, kind, diff_lines)


async def _build_edit_plan(
    req: EditRequest, workspace: Path, corrector: ContentCorrector
) -> Plan:
    """
    Build a plan for editing a file by replacing content.
    
    Args:
        req: The edit request
        workspace: Workspace root directory
        corrector: Content corrector to apply
        
    Returns:
        Plan containing the operation details
        
    Raises:
        ValueError: If file doesn't exist and old string is non-empty, or if
                   old string is not found the expected number of times
    """
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
    print(f"[_build_edit_plan] kind={kind} file={req.file_path}")
    return Plan(original, corrected, kind, diff_lines)


async def build_plan(
    req: Request, workspace: Path, corrector: ContentCorrector | None = None
) -> Plan:
    """
    Build an execution plan for a file operation request.
    
    Args:
        req: The file operation request (write or edit)
        workspace: Workspace root directory
        corrector: Optional content corrector to apply
        
    Returns:
        Plan containing the operation details
        
    Raises:
        ValueError: If path validation fails or content validation fails
    """
    print(f"[build_plan] request={type(req).__name__} file={req.file_path}")
    if (err := validate_path(req.file_path, workspace)) is not None:
        raise ValueError(err["message"])
    if isinstance(req, WriteRequest) and (err := validate_content(req.content)):
        raise ValueError(err["message"])

    c = corrector or IdentityCorrector()
    if isinstance(req, WriteRequest):
        return await _build_write_plan(req, workspace, c)
    return await _build_edit_plan(req, workspace, c)


async def commit_plan(plan: Plan) -> None:
    """
    Commit a plan by writing the corrected content to the file system.
    
    Args:
        plan: The plan to commit
        
    Raises:
        Exception: If file writing fails, the temporary file is cleaned up
    """
    if plan.kind == FileOperation.NOOP:
        print("[commit_plan] NOOP – nothing to do")
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
        print(f"[commit_plan] committed {p}")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ------------- Public API ----------------------------------------------------
async def write_file(
    req: WriteRequest, workspace: Path, corrector: ContentCorrector | None = None
) -> Plan:
    """
    Write or overwrite a file with new content.
    
    Args:
        req: The write request
        workspace: Workspace root directory
        corrector: Optional content corrector to apply
        
    Returns:
        Plan containing the operation details
    """
    print(f"[write_file] file={req.file_path}")
    plan = await build_plan(req, workspace, corrector)
    await commit_plan(plan)
    return plan


async def edit_file(
    req: EditRequest, workspace: Path, corrector: ContentCorrector | None = None
) -> Plan:
    """
    Edit a file by replacing old content with new content.
    
    Args:
        req: The edit request
        workspace: Workspace root directory
        corrector: Optional content corrector to apply
        
    Returns:
        Plan containing the operation details
    """
    print(f"[edit_file] file={req.file_path}")
    plan = await build_plan(req, workspace, corrector)
    await commit_plan(plan)
    return plan


# ------------------ Tools for agents --------------------------------


async def fs_write(file_path: str, content: str) -> list[str]:
    """
    Create or completely overwrite a file in the current working directory.

    Use this function when you need to:
    • create a brand-new file
    • replace the entire contents of an existing file

    Parameters
    ----------
    file_path : str
        Relative or absolute path to the file.  If relative, it is resolved
        against the current working directory.  Parent directories are created
        automatically if they do not exist.
    content : str
        The full text to write into the file.  Must be valid UTF-8.

    Returns
    -------
    list[str]
        A unified-diff of the change that would be applied (empty list if the
        file already contains exactly the proposed content).

    Raises
    ------
    ValueError
        If the resolved path lies outside the current workspace or the content
        cannot be encoded as UTF-8.
    """
    print(f"[fs_write] file_path={file_path}")
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
    """
    Perform a precise, line-aware edit on an existing file.

    Use this function when you need to:
    • change a specific substring or block of code
    • insert new text at a known location (set `old_string` to the marker
      you want to replace)
    • delete a block (set `new_string` to an empty string)

    The function performs a literal string replacement and validates that the
    expected number of matches is found before applying the change.

    Parameters
    ----------
    file_path : str
        Relative or absolute path to the file.  If relative, it is resolved
        against the current working directory.
    old_string : str
        Exact substring to locate in the current file content.  Leading/trailing
        whitespace and newlines are significant.
    new_string : str
        Replacement text to insert in place of `old_string`.
    expected_replacements : int, default 1
        Number of times `old_string` must appear for the edit to succeed.
        Set to 0 to allow creation of a new file (in which case `old_string`
        must be empty).

    Returns
    -------
    list[str]
        A unified-diff of the change that would be applied.

    Raises
    ------
    ValueError
        • If the resolved path lies outside the current workspace.
        • If `old_string` is not found the expected number of times.
        • If the file does not exist and `old_string` is non-empty.
    """
    print(
        f"[fs_edit] file_path={file_path} "
        f"old_string={repr(old_string)} new_string={repr(new_string)} "
        f"expected_replacements={expected_replacements}"
    )
    req = EditRequest(
        file_path=AbsolutePath(Path(file_path).resolve()),
        old=old_string,
        new=new_string,
        expect=expected_replacements,
    )
    plan = await build_plan(req, Path.cwd())
    return plan.diff_lines
