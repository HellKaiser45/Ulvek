"""
codebase.py – single public helper `inspect_cwd()` for rich CWD inspection.
"""

from __future__ import annotations

import ast
import os
import stat as _stat
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _format_time(epoch: float) -> str:
    """Return ISO-8601 local-time string from epoch seconds."""
    return datetime.fromtimestamp(epoch).isoformat(sep=" ", timespec="seconds")


def _type_hint(p: Path) -> str:
    """Return a short type hint for a path."""
    if p.is_dir():
        return "dir"
    suffix = p.suffix.lower()
    if suffix == ".py":
        return "py"
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix in {".txt", ".text"}:
        return "txt"
    if suffix in {".json"}:
        return "json"
    if suffix in {".yml", ".yaml"}:
        return "yaml"
    return suffix.lstrip(".") or "file"


def _tree(root: Path, max_depth: int = 6) -> str:
    """
    Build an indented tree string for everything under `root`.
    Each line contains: name | last-mod | size | type-hint
    """
    lines: List[str] = []

    def _walk(path: Path, prefix: str = "", depth: int = 0) -> None:
        if depth > max_depth:
            return
        try:
            st = path.stat()
        except OSError:
            st = None

        # Build annotation
        if st is None:
            meta = "<no permission>"
        else:
            mtime = _format_time(st.st_mtime)
            if path.is_dir():
                meta = f"{mtime}  <dir>"
            else:
                meta = f"{mtime}  {st.st_size:>8} bytes"

        hint = _type_hint(path)
        lines.append(f"{prefix}{path.name}  |  {meta}  |  {hint}")

        if path.is_dir():
            try:
                entries = sorted(path.iterdir())
            except OSError:
                return
            for idx, entry in enumerate(entries):
                is_last = idx == len(entries) - 1
                next_prefix = prefix + ("    " if is_last else "│   ")
                pointer = "└── " if is_last else "├── "
                _walk(entry, next_prefix + pointer, depth + 1)

    _walk(root)
    return "\n".join(lines)


def _ast_summary(py_file: Path) -> str:
    """
    Return a compact AST dump for a Python file:
    imports, top-level classes, and functions.
    """
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except Exception as exc:
        return f"    <parse error: {exc}>"

    parts: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(a.name for a in node.names)
            parts.append(f"from {module} import {names}")
        elif isinstance(node, ast.ClassDef):
            parts.append(f"class {node.name}")
        elif isinstance(node, ast.FunctionDef):
            parts.append(f"def {node.name}()")
        elif isinstance(node, ast.AsyncFunctionDef):
            parts.append(f"async def {node.name}()")

    if not parts:
        return "    <empty module>"
    return "\n".join(f"    {line}" for line in parts)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def inspect_cwd() -> str:
    """
    Return a rich, human-readable string describing the current working directory.
    """
    root = Path.cwd().resolve()
    header = f"CWD: {root}\n"
    tree_block = _tree(root)
    py_files = sorted(root.rglob("*.py"))

    ast_blocks: List[str] = []
    for py in py_files:
        rel = py.relative_to(root)
        ast_blocks.append(f"\nAST summary for {rel}:")
        ast_blocks.append(_ast_summary(py))

    return header + "\n" + tree_block + "".join(ast_blocks)


# --------------------------------------------------------------------------- #
# CLI convenience
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print(inspect_cwd())
