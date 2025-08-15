import difflib
import pathlib
import textwrap
from pathlib import Path
from pydantic import BaseModel, Field


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


# ---------- Pydantic-AI tools ------------------------------------------------
async def write_file(params: WriteParams) -> str:
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
    new_content = textwrap.dedent(params.content).lstrip()
    tmp = src.with_suffix(src.suffix + ".tmp")
    tmp.write_text(new_content)
    tmp.replace(src)
    return f"{'Overwrote' if exists else 'Created'} {params.file_path}"


async def edit_file(params: EditParams) -> str:
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

    tmp = src.with_suffix(src.suffix + ".tmp")
    tmp.write_text(new_content)
    tmp.replace(src)
    return f"Successfully applied edit to {params.file_path}"
