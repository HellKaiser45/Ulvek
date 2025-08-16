from enum import StrEnum


class MainRoutes(StrEnum):
    CHAT = "chat"
    CONTEXT = "context"
    CODE = "code"
    PLAN = "plan"


class PlannerRoutes(StrEnum):
    PLAN = "plan"
    USERFEEDBACK = "user_feedback"
    USER_APPROVAL = "user_approval"
    CODE = "code"


class CodeRoutes(StrEnum):
    CODE = "code"
    USERFEEDBACK = "user_feedback"
    USER_APPROVAL = "user_approval"
    AGENTFEEDBACK = "agent_feedback"
    APPLYEDIT = "apply_edit"


class Interraction(StrEnum):
    APPROVAL = "approval"
    FEEDBACK = "feedback"
    INTOOLFEEDBACK = "intool_feedback"
