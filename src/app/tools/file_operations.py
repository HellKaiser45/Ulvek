import subprocess
from pathlib import Path
from pydantic import FilePath
from src.app.agents.schemas import (
    FileOperationType,
    FilePlan,
    TextEdit,
    Range,
    Position,
    EditFileOperation,
)
from src.app.utils.logger import get_logger
from src.app.tools.tools_schemas import (
    LineContentOutput,
    RangeOutput,
    ReadFileContentOutput,
    FindTextInFileOutput,
)
from src.app.utils.converters import token_count, truncate_content_by_tokens
from src.app.config import settings

logger = get_logger(__name__)

# ----------------------------FIle Reading operations--------------------------
# ----------------------------Functions used as tools -------------------------


def get_line_content(file_path: Path | FilePath, line_number: int) -> LineContentOutput:
    """Get content of specific line (1-indexed)"""

    logger.debug(f"Reading line {line_number} from file: {file_path}")
    try:
        lines = read_file_content(file_path).content.splitlines()
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return LineContentOutput(
            status="error",
            error_message=str(e),
            content="",
            file_path=file_path,
            line_number=line_number,
        )

    if 1 <= line_number <= len(lines):
        content = lines[line_number - 1]
        logger.debug(f"Retrieved content from line {line_number}: {content[:50]}...")

        return LineContentOutput(
            status="ok",
            content=content,
            file_path=file_path,
            line_number=line_number,
        )

    else:
        error_msg = f"Line {line_number} not found in {file_path}"
        logger.error(error_msg)

        return LineContentOutput(
            status="no_results",
            content="",
            file_path=file_path,
            line_number=line_number,
        )


def get_range_content(
    file_path: Path | FilePath, start_line: int, end_line: int
) -> RangeOutput:
    """Get content of line range (1-indexed, inclusive)"""

    logger.debug(f"Reading lines {start_line}-{end_line} from file: {file_path}")
    try:
        lines = read_file_content(file_path).content.splitlines()
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return RangeOutput(
            status="error",
            error_message=str(e),
            content="",
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        )

    if start_line < 1 or end_line > len(lines) or start_line > end_line:
        error_msg = f"Invalid range {start_line}-{end_line} in {file_path}"
        logger.error(error_msg)

        return RangeOutput(
            status="no_results",
            error_message=error_msg,
            content="",
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        )

    content = "\n".join(lines[start_line - 1 : end_line])
    logger.debug(f"Retrieved content from {end_line - start_line + 1} lines")

    return RangeOutput(
        status="ok",
        content=content,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
    )


def read_file_content(file_path: Path | FilePath) -> ReadFileContentOutput:
    """Read file content as string"""

    logger.debug(f"Reading content from file: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
        logger.debug(f"Successfully read {len(content)} characters from {file_path}")
        return ReadFileContentOutput(
            status="ok",
            content=content,
            file_path=file_path,
        )

    except UnicodeDecodeError:
        logger.warning(
            f"Unicode decode error for {file_path}, using replacement characters"
        )
        content = file_path.read_text(encoding="utf-8", errors="replace")
        logger.debug(
            f"Read {len(content)} characters from {file_path} with replacements"
        )
        return ReadFileContentOutput(
            status="ok",
            content=content,
            file_path=file_path,
        )

    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return ReadFileContentOutput(
            status="error",
            error_message=str(e),
            content="",
            file_path=file_path,
        )


def find_text_in_file(
    file_path: Path | FilePath, search_text: str
) -> FindTextInFileOutput:
    """Find all occurrences of text in file, return positions"""
    logger.debug(f"Searching for text '{search_text}' in file: {file_path}")
    try:
        content = read_file_content(file_path).content
        positions = []

        for line_num, line in enumerate(content.splitlines()):
            start = 0
            while True:
                pos = line.find(search_text, start)
                if pos == -1:
                    break
                positions.append(Position(line=line_num, character=pos))
                start = pos + 1
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return FindTextInFileOutput(
            status="error",
            error_message=str(e),
            positions=[],
        )

    logger.info(f"Found {len(positions)} occurrences of '{search_text}' in {file_path}")
    return FindTextInFileOutput(status="ok", positions=positions)


def position_to_offset(content: str, position: Position) -> int:
    """Convert Position to character offset in string"""

    logger.debug(
        f"Converting position (line={position.line}, char={position.character}) to offset"
    )
    lines = content.splitlines(keepends=True)

    if position.line >= len(lines):
        offset = len(content)
        logger.debug(f"Position line exceeds content, returning end offset: {offset}")
        return offset

    offset = sum(len(line) for line in lines[: position.line])
    line_content = lines[position.line] if position.line < len(lines) else ""
    character_pos = min(position.character, len(line_content.rstrip("\n\r")))
    final_offset = offset + character_pos
    logger.debug(f"Calculated offset: {final_offset}")
    return final_offset


def offset_to_position(content: str, offset: int) -> Position:
    """Convert character offset to Position"""
    lines = content.splitlines(keepends=True)
    current_offset = 0

    for line_num, line in enumerate(lines):
        if current_offset + len(line) > offset:
            character = offset - current_offset
            position = Position(line=line_num, character=character)

            return position
        current_offset += len(line)

    position = Position(line=len(lines), character=0)

    return position


# ----------------------------File Writing operations--------------------------


def write_file_content(file_path: Path, content: str) -> None:
    """Write content to file, creating directories if needed"""
    logger.info(f"Writing {len(content)} characters to file: {file_path}")
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured parent directories exist for: {file_path}")
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Successfully wrote content to {file_path}")
    except Exception as e:
        logger.error(f"Failed to write content to {file_path}: {e}")
        raise


def apply_text_edit(content: str, edit: TextEdit) -> str:
    """Apply a single TextEdit to content"""
    start_offset = position_to_offset(content, edit.range.start)
    end_offset = position_to_offset(content, edit.range.end)
    original_text = content[start_offset:end_offset]

    logger.debug(
        f"Applying text edit: replacing '{original_text}' with '{edit.new_text}' "
        f"at range {edit.range.start.line}:{edit.range.start.character}-{edit.range.end.line}:{edit.range.end.character}"
    )

    result = content[:start_offset] + edit.new_text + content[end_offset:]
    logger.debug(
        f"Text edit applied, content size changed from {len(content)} to {len(result)} characters"
    )
    return result


def apply_text_edits(content: str, edits: list[TextEdit]) -> str:
    """Apply multiple TextEdits (must be non-overlapping, sorted by position)"""
    logger.debug(f"Applying {len(edits)} text edits")
    sorted_edits = sorted(
        edits, key=lambda e: position_to_offset(content, e.range.start), reverse=True
    )
    logger.debug("Sorted edits by position in reverse order")

    result = content
    for i, edit in enumerate(sorted_edits):
        logger.debug(f"Applying edit {i + 1}/{len(edits)}")
        result = apply_text_edit(result, edit)

    logger.info(
        f"Applied {len(edits)} text edits, final content size: {len(result)} characters"
    )
    return result


def apply_unified_diff(file_path: Path, diff: str) -> None:
    """Apply unified diff using system patch command"""
    import tempfile

    logger.info(f"Applying unified diff to file: {file_path}")
    logger.debug(f"Diff content:\n{diff}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
        f.write(diff)
        temp_patch = f.name

    try:
        logger.debug(f"Created temporary patch file: {temp_patch}")
        result = subprocess.run(
            ["patch", "-p0", str(file_path)],
            input=diff,
            text=True,
            capture_output=True,
            cwd=file_path.parent,
        )

        if result.returncode != 0:
            error_msg = (
                f"Patch failed with return code {result.returncode}: {result.stderr}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        else:
            logger.info(f"Successfully applied patch to {file_path}")

    except Exception as e:
        logger.error(f"Exception during patch application: {e}")
        raise
    finally:
        try:
            Path(temp_patch).unlink(missing_ok=True)
            logger.debug(f"Cleaned up temporary patch file: {temp_patch}")
        except Exception as e:
            logger.warning(f"Failed to clean up temporary patch file {temp_patch}: {e}")


def execute_file_operation(
    operation: FileOperationType, base_path: Path = Path(".")
) -> None:
    """Execute a single file operation"""
    logger.info(f"Executing file operation: {operation.kind}")

    if operation.kind == "noop":
        logger.info(f"No-op operation: {operation.reason}")
        print(f"No-op: {operation.reason}")
        return

    if not hasattr(operation, "path"):
        logger.warning("Operation has no path attribute, skipping")
        return

    file_path = base_path / operation.path
    logger.debug(f"Resolved file path: {file_path}")

    match operation.kind:
        case "create":
            logger.info(f"Creating file: {file_path}")
            if file_path.exists():
                error_msg = f"File already exists: {file_path}"
                logger.error(error_msg)
                raise FileExistsError(error_msg)
            write_file_content(file_path, operation.content)

        case "delete":
            logger.info(f"Deleting file: {file_path}")
            if not file_path.exists():
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
            file_path.unlink()
            logger.info(f"Successfully deleted file: {file_path}")

        case "replace":
            logger.info(f"Replacing content in file: {file_path}")
            write_file_content(file_path, operation.content)

        case "edit":
            logger.info(f"Editing file: {file_path}")
            if not file_path.exists():
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)

            content = read_file_content(file_path).content
            new_content = apply_text_edits(content, operation.edits)
            write_file_content(file_path, new_content)
            logger.info(f"Successfully edited file: {file_path}")

        case "patch":
            logger.info(f"Applying patch to file: {file_path}")
            if not file_path.exists():
                error_msg = f"File not found: {file_path}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
            apply_unified_diff(file_path, operation.diff)
            logger.info(f"Successfully applied patch to file: {file_path}")


def execute_file_plan(plan: FilePlan, base_path: Path = Path(".")) -> None:
    """Execute all operations in a file plan"""
    logger.info(f"Executing file plan: {plan.summary}")
    logger.debug(f"Plan contains {len(plan.operations)} operations")
    print(f"Executing plan: {plan.summary}")

    for i, operation in enumerate(plan.operations):
        try:
            logger.debug(
                f"Executing operation {i + 1}/{len(plan.operations)}: {operation.kind}"
            )
            execute_file_operation(operation, base_path)
            logger.info(
                f"✓ Operation {i + 1}/{len(plan.operations)} completed: {operation.kind}"
            )
            print(f"✓ Operation {i + 1}/{len(plan.operations)}: {operation.kind}")
        except Exception as e:
            logger.error(f"✗ Operation {i + 1}/{len(plan.operations)} failed: {e}")
            print(f"✗ Operation {i + 1}/{len(plan.operations)} failed: {e}")
            raise


def create_replace_edit(
    file_path: Path, search_text: str, replace_text: str
) -> EditFileOperation:
    """Create an edit operation to replace first occurrence of text"""
    logger.info(
        f"Creating replace edit for '{search_text}' -> '{replace_text}' in {file_path}"
    )
    positions = find_text_in_file(file_path, search_text).positions

    if not positions:
        error_msg = f"Text not found: {search_text}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    start_pos = positions[0]
    end_pos = Position(
        line=start_pos.line, character=start_pos.character + len(search_text)
    )

    edit = TextEdit(range=Range(start=start_pos, end=end_pos), new_text=replace_text)
    operation = EditFileOperation(path=str(file_path), edits=[edit])

    logger.debug(
        f"Created edit operation with range {start_pos.line}:{start_pos.character}-{end_pos.line}:{end_pos.character}"
    )
    return operation
