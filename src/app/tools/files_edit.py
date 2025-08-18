import pathlib
import textwrap
from pathlib import Path
import re

# ---------- Helpers ----------------------------------------------------------


def _ensure_in_workspace(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise ValueError(f"Path must be inside workspace {Path.cwd()}")


# ---------- Pydantic-AI tools ------------------------------------------------


async def write_file(file_path: str, content: str) -> str:
    """
    Create a new file.

    """
    src = pathlib.Path(file_path)
    try:
        _ensure_in_workspace(src)
    except ValueError as e:
        return str(e)

    if src.exists():
        return f"File already exists: {file_path}"

    new_content = textwrap.dedent(content).lstrip()
    tmp = src.with_suffix(src.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(new_content)
    tmp.replace(src)
    return f"Created {file_path}"


async def edit_file(file_path: str, old: str, new: str) -> str:
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
    src = pathlib.Path(file_path)

    try:
        _ensure_in_workspace(src)
    except ValueError as e:
        return str(e)

    if not src.exists():
        return f"File not found: {file_path}"

    original = src.read_text()
    search = textwrap.dedent(old).strip()

    if search:
        occurrences = [m.start() for m in re.finditer(re.escape(search), original)]
        if not occurrences:
            return f"Fragment not found in {file_path}"
        if len(occurrences) > 1:
            return f"Fragment occurs multiple times in {file_path}, edit is ambiguous"

        new_content = original.replace(old, new, 1)

        tmp = src.with_suffix(src.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(new_content)
        tmp.replace(src)
        return f"Successfully applied edit to {file_path}"

    if search == textwrap.dedent(original).strip():
        return "No change applied (identical)."

    else:
        return " No valid edits found."


async def add_to_file(file_path: str, new_content: str, line: int | None = None) -> str:
    """
    Insert new content into a file at a specific line.

    Parameters
    ----------
    file_path : str
        Path to the file.
    new_content : str
        Content to insert.
    line : int | None
        1-based line number where to insert the content.
        If None → append at end of file.
        If larger than file length → append at end.

    Returns
    -------
    str
        Success or failure message.
    """
    src = pathlib.Path(file_path)
    try:
        _ensure_in_workspace(src)
    except ValueError as e:
        return str(e)

    if not src.exists():
        return f"File not found: {file_path}"

    lines = src.read_text().splitlines(keepends=True)
    insertion = textwrap.dedent(new_content).lstrip() + "\n"

    if line is None or line > len(lines):
        # append
        lines.append(insertion)
    else:
        # insert before given line index
        idx = max(0, line - 1)
        lines.insert(idx, insertion)

    tmp = src.with_suffix(src.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("".join(lines))
    tmp.replace(src)

    return f"Inserted content into {file_path} at line {line or 'EOF'}"
