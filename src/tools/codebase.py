import asyncio
import aiofiles
import ast
import json
from pydantic import BaseModel
import os
from typing import List, Set
import fnmatch


class FileAnalysis(BaseModel):
    file_path: str
    functions: list[str]
    imports: list[str]
    classes: list[str]
    tokens_count: int


async def parse_gitignore(root_path: str) -> tuple[Set[str], Set[str]]:
    """Parse .gitignore file and return patterns for dirs and files to ignore"""

    gitignore_path = os.path.join(root_path, ".gitignore")
    ignore_dirs = set()
    ignore_files = set()

    if not os.path.exists(gitignore_path):
        return ignore_dirs, ignore_files

    try:
        async with aiofiles.open(gitignore_path, "r", encoding="utf-8") as f:
            lines = await f.readlines()

            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Patterns ending with / are directories
                if line.endswith("/"):
                    ignore_dirs.add(line.rstrip("/"))
                else:
                    # Check if pattern contains wildcards
                    if any(c in line for c in ["*", "?", "[", "]"]):
                        # We'll handle wildcards during traversal
                        ignore_files.add(line)
                    else:
                        if "/" in line:
                            # This is a path with subdirectories
                            parts = line.split("/")
                            if parts[-1]:
                                ignore_files.add(parts[-1])
                            else:
                                ignore_dirs.add(parts[-2])
                        else:
                            # Simple filename
                            ignore_files.add(line)
    except Exception as e:
        print(f"⚠️ Could not parse .gitignore: {str(e)}")

    return ignore_dirs, ignore_files


def should_ignore(path: str, ignore_dirs: Set[str], ignore_files: Set[str]) -> bool:
    """Check if path should be ignored based on gitignore patterns"""
    rel_path = os.path.relpath(path, os.getcwd())

    # Check directory patterns
    for part in rel_path.split(os.sep):
        if part in ignore_dirs:
            return True

    # Check file patterns with wildcards
    for pattern in ignore_files:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(
            os.path.basename(rel_path), pattern
        ):
            return True

    return False


async def process_file(file_path: str) -> str:
    try:
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()
            print(f"📄 Processed file: {file_path}")
            return content
    except UnicodeDecodeError:
        print(f"⚠️ Could not read file (binary?): {file_path}")
    except Exception as e:
        print(f"❌ Error processing file {file_path}: {str(e)}")
    return ""


async def output_directory_tree(base_file_path: str = os.getcwd()) -> List[str]:
    """Output directory tree while ignoring virtual envs, config folders, and .lock files"""

    print(f"🚀 Starting async analysis of {base_file_path}")

    # Dossiers à ignorer (venv, node_modules, etc.)
    IGNORE_DIRS = {
        "venv",
        ".venv",
        "env",
        ".env",
        "__pycache__",
        ".git",
        "node_modules",
        ".mypy_cache",
    }

    # Fichiers à ignorer (.env, *.lock, etc.)
    IGNORE_FILES = {".env", ".env.local", ".env.dev", ".env.prod", "__init__.py"}
    IGNORE_EXTENSIONS = {".lock", ".db"}  # <-- Nouveau: extensions à ignorer

    tasks = []

    for root, dirs, files in os.walk(base_file_path, topdown=True):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            file_path = os.path.join(root, file)

            # Ignorer les fichiers dans IGNORE_FILES ou avec une extension bloquée
            if file in IGNORE_FILES or any(
                file.endswith(ext) for ext in IGNORE_EXTENSIONS
            ):
                print(f"⚡ Ignoring file: {file_path}")
                continue

            tasks.append(process_file(file_path))

    return await asyncio.gather(*tasks)
