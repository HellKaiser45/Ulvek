from pydantic import BaseModel, Field, FilePath
from typing import Literal, Optional
from src.app.workflow.enums import MainRoutes


# ----------------evaluator_agent-------------------
class Evaluation(BaseModel):
    """Defines the structured feedback for evaluating an agent's output."""

    grade: bool = Field(
        ...,
        description="A strict boolean outcome: `true` if the work is acceptable, `false` if it requires changes.",
    )
    feedback: str = Field(
        ..., description="A high-level, human-readable summary of the evaluation."
    )
    strengths: list[str] = Field(
        ...,
        description="List specific aspects of the output that were well-executed to reinforce good behavior.",
    )
    weaknesses: list[str] = Field(
        ...,
        description="List specific aspects of the output that were incorrect or lacking to provide clear, actionable critique.",
    )
    suggested_revision: str | None = Field(
        default=None,
        description="If grade is `false`, provide a concrete plan to *fix* the current output. This is for iterative improvement.",
    )
    alternative_approach: str | None = Field(
        default=None,
        description="If grade is `false` and the core strategy is flawed, suggest a completely *different way* to solve the task.",
    )


# ----------------coding_agent----------------------
class Position(BaseModel):
    """A zero-indexed character position within a file."""

    line: int = Field(..., description="Line number, starting from 0.")
    character: int = Field(
        ..., description="Character offset within the line, starting from 0."
    )


class Range(BaseModel):
    """A zero-indexed text range in a document, with an exclusive end position."""

    start: Position
    end: Position


class TextEdit(BaseModel):
    """A single, precise text replacement operation within a file."""

    range: Range = Field(..., description="The exact range of text to be replaced.")
    new_text: str = Field(
        ..., description="The new text to insert in place of the old range."
    )


class FileOperation(BaseModel):
    """An abstract base model for a single operation on a file."""

    path: str = Field(..., description="File path relative to the project root.")


class CreateFileOperation(FileOperation):
    """Use to create a new file from scratch."""

    kind: Literal["create"] = "create"
    content: str = Field(
        ..., description="The complete and final content of the new file."
    )


class DeleteFileOperation(FileOperation):
    """Use to remove an existing file from the project."""

    kind: Literal["delete"] = "delete"


class ReplaceFileOperation(FileOperation):
    """Use for a complete rewrite of a file. Best when edits are too extensive for a patch."""

    kind: Literal["replace"] = "replace"
    content: str = Field(
        ...,
        description="The new, complete content that will overwrite the entire file.",
    )


class EditFileOperation(FileOperation):
    """Use for precise, surgical changes using character positions. Best for when a diff is difficult or unreliable."""

    kind: Literal["edit"] = "edit"
    edits: list[TextEdit] = Field(
        ..., description="An ordered list of text edits to apply to the file."
    )


class PatchFileOperation(FileOperation):
    """The default choice for most modifications. Use to apply a standard `unified diff` format patch."""

    kind: Literal["patch"] = "patch"
    diff: str = Field(
        ..., description="The content of the patch in the unified diff format."
    )


class NoOpOperation(BaseModel):
    """Use if the request requires no code changes (e.g., the code is already correct)."""

    kind: Literal["noop"] = "noop"
    reason: str = Field(
        ..., description="A clear explanation for why no operation was necessary."
    )


FileOperationType = (
    CreateFileOperation
    | DeleteFileOperation
    | ReplaceFileOperation
    | EditFileOperation
    | PatchFileOperation
    | NoOpOperation
)


class FilePlan(BaseModel):
    """Represents a complete set of file modifications required to complete a coding task."""

    task_id: int | None = Field(
        default=None,
        description="The ID of the task this plan corresponds to, if applicable.",
    )
    summary: str = Field(
        ...,
        description="A brief, one-sentence executive summary of the planned changes.",
    )
    operations: list[FileOperationType] = Field(
        ..., description="The specific, ordered list of file operations to be executed."
    )
    research_notes: str | None = Field(
        default=None, description="Optional notes from any preliminary research phase."
    )
    reasoning_logic: str = Field(
        ...,
        description="Explain the step-by-step thought process that led to this plan. Justify *why* these specific operations were chosen.",
    )


# ----------------orchestrator_agent----------------
class ExecutionStep(BaseModel):
    """A single, atomic task within a larger ProjectPlan."""

    task_id: int = Field(
        ...,
        description="A unique, sequential identifier for this task (e.g., 1, 2, 3).",
    )
    description: str = Field(
        ...,
        description="The imperative instruction for this task. What is the single action to be performed?",
    )
    guidelines: list[str] = Field(
        default_factory=list,
        description="Optional high-level advice for the agent executing this step.",
    )
    id_dependencies: list[int] = Field(
        default_factory=list,
        description="A list of `task_id`s that must be completed before this task can start.",
    )
    target_resource: str = Field(
        ..., description="The primary file, module, or component this task operates on."
    )
    file_dependencies: list[str] = Field(
        default_factory=list,
        description="A list of file paths that this task will read from or is related to.",
    )
    pitfalls: list[str] = Field(
        default_factory=list,
        description="Identify potential risks or edge cases to de-risk this step for the executing agent.",
    )


class ProjectPlan(BaseModel):
    """A comprehensive, multi-step plan for complex tasks, designed to be executed by other agents."""

    planning_strategy: str = Field(
        ...,
        description="Explain the high-level technical approach and the reasoning behind the decomposition of tasks.",
    )
    steps: list[ExecutionStep] = Field(
        ...,
        description="The ordered list of execution steps. Must follow dependency order.",
    )


# ----------------context_retriever_agent-----------
class FileSnippet(BaseModel):
    """A relevant code excerpt or content from a file within the project."""

    file_path: FilePath = Field(..., description="The full path to the file.")
    text: str = Field(
        ..., description="The extracted, relevant content of the file snippet."
    )
    range: Optional[Range] = Field(
        default=None,
        description="The specific line and character range of the snippet, if available.",
    )


class ExternalDocChunk(BaseModel):
    """A documentation excerpt retrieved for an external library, package, or API."""

    source: str = Field(
        ...,
        description="The name of the documentation source (e.g., 'FastAPI', 'pytest', 'React').",
    )
    content: str = Field(
        ...,
        description="The raw markdown or plain-text excerpt from the documentation.",
    )


class GatheredContext(BaseModel):
    """A structured knowledge bundle containing all context gathered by a research agent."""

    summary: str = Field(
        ...,
        description="One-sentence overview of the findings and their relevance to the original query.",
    )
    snippets: list[FileSnippet] = Field(
        default_factory=list,
        description="A list of relevant code snippets from project files.",
    )
    external_docs: list[ExternalDocChunk] = Field(
        default_factory=list,
        description="A list of relevant documentation for external libraries.",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Explicitly list what you *could not find*. This is critical for the next agent to know.",
    )
    questions: list[str] = Field(
        default_factory=list,
        description="List clarifying questions for the *user* if the context is insufficient to proceed.",
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="A list of tool names invoked during research, for auditing.",
    )


# --------------Task classification agent--------------
class TaskType(BaseModel):
    """Defines the initial classification of a user's request to route it to the correct agent."""

    task_type: Literal[
        MainRoutes.CHAT, MainRoutes.CONTEXT, MainRoutes.PLAN, MainRoutes.CODE
    ] = Field(
        ...,
        description=f"""
        The final classification.
        - `{MainRoutes.CHAT}`: For general Q&A or explanations. No code changes needed.
        - `{MainRoutes.CONTEXT}`: When the request is vague, requiring *information gathering* before action.
        - `{MainRoutes.PLAN}`: For complex features requiring *architectural design* and decomposition into multiple steps.
        - `{MainRoutes.CODE}`: For simple, specific, and immediately actionable code changes.
        """,
    )
    reasoning: str = Field(
        ...,
        description="Provide the justification for the chosen classification, explaining why it fits and why the others do not.",
    )
