import aiofiles
from pydantic import BaseModel
import os
from magika import Magika
from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern


class FileAnalysis(BaseModel):
    file_path: str
    file_type: str
    mime_type: str
    description: str
    group: str


async def get_magika_instance() -> Magika:
    """Get Magika instance (kept async for potential future async needs)"""
    return Magika()


async def get_gitignore_spec(root_path: str = os.getcwd()) -> PathSpec:
    """Async .gitignore parser using aiofiles"""
    gitignore_path = os.path.join(root_path, ".gitignore")
    default_patterns = [".git/", ".git"]

    if os.path.exists(gitignore_path):
        async with aiofiles.open(gitignore_path, mode="r", encoding="utf-8") as f:
            default_patterns.extend(await f.readlines())

    return PathSpec.from_lines(GitWildMatchPattern, default_patterns)


async def get_non_ignored_files(root_path: str = os.getcwd()) -> list[str]:
    """Async file scanning with proper gitignore handling"""
    spec = await get_gitignore_spec(root_path)
    non_ignored = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [
            d
            for d in dirnames
            if not spec.match_file(os.path.relpath(os.path.join(dirpath, d), root_path))
        ]

        non_ignored.extend(
            os.path.relpath(os.path.join(dirpath, f), root_path)
            for f in filenames
            if not spec.match_file(os.path.relpath(os.path.join(dirpath, f), root_path))
        )

    return non_ignored


async def process_file(file_paths: list[str]) -> list[FileAnalysis]:
    """Async file processing pipeline"""
    m = await get_magika_instance()
    return [
        FileAnalysis(
            file_path=str(result.path),
            file_type=result.output.label,
            mime_type=result.output.mime_type,
            description=result.output.description,
            group=result.output.group,
        )
        for result in m.identify_paths(file_paths)
    ]
