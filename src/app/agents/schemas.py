from pydantic import BaseModel, Field
from typing import Literal
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
class FileContext(BaseModel):
    """
    single file related information
    """

    file_path: str = Field(
        ..., description="path to a relevant file providing information"
    )
    file_dependencies: list[str] | None = Field(
        default_factory=list,
        description="list of the other files that are used by the file",
    )
    package_dependencies: list[str] | None = Field(
        default_factory=list,
        description="list of the packages that are used by the file",
    )
    file_description: str = Field(
        ..., description="breif description of the file structure and content"
    )
    relevance_reason: str = Field(
        ...,
        description="justification on the reason(s) why and how this file is relevant to the task",
    )


class ExternalContext(BaseModel):
    """
    relevant documentation or additional user provided information
    """

    source: Literal["documentation", "user"] = Field(
        ..., description="source of the information"
    )
    title: str = Field(
        ...,
        description="title of the source if source is 'documentation'. e.g., library name, docs page title",
    )
    content: str = Field(
        ..., description="raw content/output of the source or tool if it is relevant"
    )
    relevance_reason: str = Field(
        ...,
        description="justification on the reason(s) why and how this information is relevant to the task",
    )


class InterestingCodeSnippet(BaseModel):
    """
    A code snippet that is relevant to the task
    """

    source: Literal["codebase", "documentation", "user"] = Field(
        ..., description="source of the code snippet"
    )
    file_path: str | None = Field(
        None,
        description="path to the file containing the code snippet if source is 'codebase'",
    )
    start_line: int | None = Field(
        None,
        description="line number of the start of the code snippet if source is 'codebase'",
    )
    end_line: int | None = Field(
        None,
        description="line number of the end of the code snippet if source is 'codebase'",
    )
    documentation_provider: str | None = Field(
        None,
        description="name of the documentation provider if source is 'documentation' e.g., library name",
    )
    code: str = Field(..., description="the code snippet")
    description: str = Field(..., description="a description of the code snippet")
    relevance_reason: str = Field(
        ...,
        description="justification on the reason(s) why and how this code snippet is relevant to the task",
    )


class ProjectStructureOverview(BaseModel):
    """A summary of the project's structure."""

    key_directories: list[str] = Field(
        ..., description="List of important directories."
    )
    key_files: list[str] = Field(
        ..., description="List of important files (entry points, configs)."
    )
    technologies_used: list[str] = Field(
        ..., description="Key libraries/technologies identified."
    )
    summary: str = Field(
        ..., description="A brief narrative summary of the project structure."
    )


class AssembledContext(BaseModel):
    """
    Structured output from the gather_docs_context tool
    Should provide the necessary information for subsequent tasks
    """

    retrieval_summary: str = Field(
        ...,
        description="A summary/inventory of the gathered context from the tools used",
    )

    project_structure: ProjectStructureOverview = Field(
        ...,
        description="A summary of the project's structure, layout and key components.",
    )
    code_snippets: list[InterestingCodeSnippet] = Field(
        default_factory=list,
        description="A list of code snippets relevant to the task.",
    )
    external_context: list[ExternalContext] = Field(
        default_factory=list,
        description="Relevant documentation or additional user provided information.",
    )
    file_context: list[FileContext] = Field(
        default_factory=list,
        description="Relevant files content or extract and their dependencies.",
    )
    retrieval_strategy: str = Field(
        ...,
        description="A description of the strategy used to gather the context and the process of gathering it.(e.g., 'used tool a to gather X info because ...', 'searching for X to make sure ...', ...)",
    )
    context_coverage_score: float = Field(
        ...,
        description="Score 0-1: what fraction of the user query can be answered with this context",
        ge=0.0,
        le=1.0,
    )
    confidence_score: float = Field(
        ...,
        description="Score 0-1: how certain you are about the gathered information",
        ge=0.0,
        le=1.0,
    )
    remaining_gaps: list[str] = Field(
        default_factory=list,
        description="Specific information still needed (max 3 items). Empty list means context is complete.",
    )
    search_intent: Literal["exploration", "specific_lookup", "dependency_mapping"] = (
        Field(
            ..., description="The primary intent behind this context gathering session"
        )
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="List of tools used in this context gathering (for cost tracking)",
    )
    context_stage: Literal["quick_scan", "focused_dive", "complete"] = Field(
        default="complete", description="Stage of context gathering completed"
    )


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
