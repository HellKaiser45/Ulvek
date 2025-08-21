from pydantic import BaseModel, Field, FilePath, DirectoryPath
from typing import Literal, Optional
from src.app.workflow.enums import MainRoutes


# ----------------evaluator_agent-------------------
class Evaluation(BaseModel):
    grade: bool = Field(..., description="true to approve, false to reject")
    feedback: str = Field(..., description="A detailed explanation of the feedback")

    strengths: list[str] = Field(
        ..., description="list of aspects of the output that were done well"
    )
    weaknesses: list[str] = Field(
        ..., description="list of aspects of the output that were lacking or incorrect"
    )
    suggested_revision: str | None = Field(
        default=None,
        description="A suggestion on how to improve the work done only if the grade is 'false'",
    )
    alternative_approach: str | None = Field(
        default=None,
        description="A suggestion on how to approach the task differently if the grade is 'revision_needed' and you think the current path is flawed",
    )


# ----------------coding_agent----------------------


class Position(BaseModel):
    """Character position in a document (0-indexed)"""

    line: int = Field(..., description="Line number (0-indexed)")
    character: int = Field(..., description="Character offset in line (0-indexed)")


class Range(BaseModel):
    """Text range in a document"""

    start: Position = Field(..., description="Start position (inclusive)")
    end: Position = Field(..., description="End position (exclusive)")


class TextEdit(BaseModel):
    """A single text edit operation"""

    range: Range = Field(..., description="Range to replace")
    new_text: str = Field(..., description="New text content")


class FileOperation(BaseModel):
    """Base class for all file operations"""

    path: str = Field(..., description="File path relative to project root")


class CreateFileOperation(FileOperation):
    """Create a new file"""

    kind: Literal["create"] = "create"
    content: str = Field(..., description="Complete file content")


class DeleteFileOperation(FileOperation):
    """Delete an existing file"""

    kind: Literal["delete"] = "delete"


class ReplaceFileOperation(FileOperation):
    """Replace entire file content"""

    kind: Literal["replace"] = "replace"
    content: str = Field(..., description="New complete file content")


class EditFileOperation(FileOperation):
    """Edit file using precise character positions"""

    kind: Literal["edit"] = "edit"
    edits: list[TextEdit] = Field(..., description="Text edits to apply")


class PatchFileOperation(FileOperation):
    """Apply unified diff patch"""

    kind: Literal["patch"] = "patch"
    diff: str = Field(..., description="Unified diff content")


class NoOpOperation(BaseModel):
    """No changes needed"""

    kind: Literal["noop"] = "noop"
    reason: str = Field(..., description="Why no operation is needed")


FileOperationType = (
    CreateFileOperation
    | DeleteFileOperation
    | ReplaceFileOperation
    | EditFileOperation
    | PatchFileOperation
    | NoOpOperation
)


class FilePlan(BaseModel):
    """AI agent output - list of file operations"""

    task_id: int | None = Field(default=None, description="id of the task")
    summary: str = Field(
        ..., description="A concise summary of all the planned changes"
    )
    operations: list[FileOperationType] = Field(
        ..., description="A list of files modifications to be performed"
    )
    research_notes: str | None = Field(
        default=None,
        description="Free-form notes from a research or information-gathering",
    )
    reasoning_logic: str = Field(
        ..., description="The internal thought process and the task breakdown"
    )


# ----------------orchestrator_agent----------------
class ExecutionStep(BaseModel):
    """
    A single, atomic, well-defined action/task within the overall plan
    """

    task_id: int = Field(..., description="a unique identifier for the task")
    description: str = Field(
        ...,
        description="a clear,concise instruction on what needs to be done in this step",
    )
    guidelines: list[str] = Field(
        default_factory=list,
        description="a list of guidelines or suggestions on how to execute this step in regards to the overall plan",
    )
    id_dependencies: list[int] = Field(
        default_factory=list,
        description="a list of 'task id' that need to be completed before this step can be executed",
    )
    target_ressource: str = Field(
        ..., description="the primarly file, module or resource this step is targeting"
    )
    file_dependencies: list[str] = Field(
        default_factory=list,
        description="a list of 'file paths' that are tightly related to this step",
    )
    pitfalls: list[str] = Field(
        default_factory=list,
        description="a list of pitfalls or things to pay attention to when executing this step. Generally things to be careful in light of the overall plan",
    )


class ProjectPlan(BaseModel):
    """
    A comprehensive, clear and structured plan of the the implementation
    """

    planning_strategy: str = Field(
        ...,
        description="explanation of how the plan answers the user's demand and the thinking process behing it",
    )
    steps: list[ExecutionStep] = Field(
        ...,
        description="The ordered list of step(s) to execute. The workflow should follow dependency order.",
    )


# ----------------context_retriever_agent-----------
class FileSnippet(BaseModel):
    file_path: FilePath
    text: str
    range: Optional[Range] = None


class ExternalDocChunk(BaseModel):
    source: str
    content: str


class GatheredContext(BaseModel):
    summary: str
    snippets: list[FileSnippet] = []
    external_docs: list[ExternalDocChunk] = []
    gaps: list[str] = []
    questions: list[str] = []
    tools_used: list[str] = []


# --------------Task classification agent--------------


class TaskType(BaseModel):
    task_type: Literal[
        MainRoutes.CHAT, MainRoutes.CONTEXT, MainRoutes.PLAN, MainRoutes.CODE
    ] = Field(
        ...,
        description=f"""
        classification of the task type based on the user's input
        {MainRoutes.CHAT}: the task is a simple chat/conversation/Q&A
        {MainRoutes.CONTEXT}: the task needs alot more information to be completed
        {MainRoutes.PLAN}: the task is huge/complex and needs to be broken down into smaller steps
        {MainRoutes.CODE}: the task is a simple coding task that can be completed right away
        """,
    )
    reasoning: str = Field(
        ..., description="Reasoning process for the task type classification"
    )
