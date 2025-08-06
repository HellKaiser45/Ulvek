from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from ..config import settings
from pydantic import BaseModel, Field
from typing import Literal
from pydantic_ai import Tool
from src.tools.interactive_tools import gather_docs_context, prompt_user
from src.tools.search_files import search_files
from src.tools.files_edit import write_file, edit_file, batch_edit
from src.tools.terminal_executor import run_command, run_commands


model = OpenAIModel(
    model_name=settings.MODEL_NAME,
    provider=OpenAIProvider(
        base_url=settings.BASE_URL,
        api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
    ),
)

azure_safety_template = """
    You are an AI assistant.

### Grounding
    - Base every factual claim on **provided sources**; cite inline.  
    - If sources are insufficient, state *“I cannot find this in the provided documents.”*

### Neutrality
    - Do **not** infer intent, sentiment, or background information.  
    - Do **not** alter dates, times, or facts.

### Professionalism
    - Keep responses concise, on-topic, and professional.  
    - Decline questions about your identity or capabilities.

### Output
    - Whenever possible, return **valid JSON or Markdown** as requested by the user.  
    - Avoid speculative language (“might”, “probably”).
    --------------------------------------------------------------------------------
    """
# -------------------------------------------------
# Agents outputs models
# -------------------------------------------------


# ----------------evaluator_agent-------------------
class detailled_feedback(BaseModel):
    """
    A detailed explanation of the feedback
    """

    feedback: str = Field(..., description="A detailed explanation of the feedback")
    strengths: list[str] = Field(
        ..., description="list of aspects of the output that were done well"
    )
    weaknesses: list[str] = Field(
        ..., description="list of aspects of the output that were lacking or incorrect"
    )
    quality_score: int = Field(
        ...,
        ge=0,
        le=10,
        description="a score from 0 to 10 that reflects the quality of the work done",
    )


class Evaluation(BaseModel):
    grade: Literal["pass", "revision_needed"] = Field(
        ..., description="the overall assessment of the worker's output"
    )
    complete_feedback: detailled_feedback = Field(
        ..., description="A detailed feedback on the work done"
    )
    confindence_score: int = Field(
        ...,
        ge=0,
        le=10,
        description="a score from 0 to 10 that reflects the confidence in the grade attribution ",
    )
    suggested_revision: str | None = Field(
        default=None,
        description="A suggestion on how to improve the work done only if the grade is 'revision_needed'",
    )
    alternative_approach: str | None = Field(
        default=None,
        description="A suggestion on how to approach the task differently if the grade is 'revision_needed' and you think the current path is flawed",
    )


# ----------------coding_agent----------------------
class FileEditOperation(BaseModel):
    """Represents a single file modification operation."""

    oparion_type: Literal["create", "edit", "delete"] = Field(
        ..., description="type of file operation"
    )
    file_path: str = Field(
        ...,
        description="path to the file being edited or created or deleted. File: [path/to/file]",
    )
    old_content: str | None = Field(
        None, description="old content of the file for 'edit'"
    )
    new_content: str | None = Field(
        None, description="new content of the file for 'edit' and 'create' operations"
    )
    diff: str | None = Field(
        None,
        description="""
        a unified diff representaion of the change
        example:
        path/to/file.py
        ```
        >>>>>>> SEARCH
        def search():
            pass
        =======
        def search():
        raise NotImplementedError()
        <<<<<<< REPLACE
        """,
    )


class ReasoningLogic(BaseModel):
    """
    The thought process and the task breakdown
    """

    description: str = Field(
        ...,
        description="A description of the reasoning logic and execution plan breakdown",
    )
    steps: list[str] = Field(
        ..., description="A list of steps in the reasoning logic and execution"
    )


class WorkerResult(BaseModel):
    """
    A comprehensive result of a worker's work.
    capture the result of diverse tasks
    """

    task_id: int | None = Field(None, description="id of the task")
    summary: str = Field(
        ..., description="A concise summary of all the work done and outcomes"
    )
    files_edited: list[FileEditOperation] | None = Field(
        None, description="A list of files modifications performed"
    )
    research_notes: str | None = Field(
        None, description="Free-form notes from a research or information-gathering"
    )
    reasoning_logic: ReasoningLogic = Field(
        ..., description="The thought process and the task breakdown"
    )
    status: Literal["success", "failure", "incomplete"] = Field(
        ..., description="Overall status of the task execution"
    )
    self_review: str = Field(
        ..., description="Agent's own assessment of the result quality and confidence."
    )
    revision_imcomplete: str | None = Field(
        None,
        description="Specific feedback on what needs to be done or changed if status is 'incomplete'",
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
    estimated_total_complexity: int = Field(
        ...,
        ge=0,
        le=10,
        description="estimated complexity of the asked task from 0 to 10",
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
        None, description="list of the other files that are used by the file"
    )
    package_dependencies: list[str] | None = Field(
        None, description="list of the packages that are used by the file"
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
    confidence: int = Field(
        ...,
        ge=0,
        le=10,
        description="Agent's confidence in the relevance and completeness of the gathered context (0 to 10) to perform the task.",
    )
    gaps_identified: list[str] | None = Field(
        None,
        description="list of potential context gaps and areas that might need further investigation to complete the task",
    )
    follow_up_actions: list[str] | None = Field(
        None,
        description="list of manual actions that needs to be done by the user before attemting to complete the task and that is not related to coding",
    )


# -------------------------------------------------
# Agents definitions
# -------------------------------------------------

evaluator_agent = Agent(
    model,
    system_prompt=(
        "You are a rigorous code reviewer. Provide actionable feedback.",
        "Return JSON with: `grade` (pass/revision_needed) and `feedback`.",
    ),
    output_type=Evaluation,
    name="evaluator_agent",
)

coding_agent = Agent(
    model,
    system_prompt=(
        "You are an expert software engineer. "
        "Return ONLY the requested code snippet and a one-line explanation.",
        "Before any calling any edit or write_file , make sure you know the file and dependencies it is using ",
        "consider the whole app in your decisions",
        "use your search_files tool to verify the exact text to replace.",
    ),
    name="coding_agent",
    output_type=WorkerResult,
    tools=[
        Tool(write_file),
        Tool(edit_file),
        Tool(search_files),
    ],
)

orchestrator_agent = Agent(
    model,
    system_prompt=(
        "You are a task-decomposition assistant. "
        "Break the request into atomic, ordered Markdown to-do items.",
    ),
    output_type=ProjectPlan,
    name="orchestrator_agent",
)

# must return the tools output to use as the context later
context_retriever_agent = Agent(
    model,
    system_prompt=(
        "you want to make sure you understand and have sufficient knowledge context."
        "keep gathering information using the tools until you estimate it is not necessary anymore. "
        "aggregate the output of the tools and return it raw",
    ),
    name="context gatherer agent",
    output_type=AssembledContext,
    tools=[
        Tool(prompt_user),
        Tool(search_files),
        Tool(gather_docs_context),
    ],
)

conversational_agent = Agent(
    model,
    system_prompt=(
        "You are a helpful, engaging AI assistant. "
        "Conduct natural conversations, remember context throughout the discussion, "
        "ask clarifying questions when needed, and provide thoughtful responses. "
        "Be empathetic, concise, and focused on being genuinely helpful.",
    ),
    name="conversational_agent",
    tools=[
        Tool(prompt_user),
    ],
)
