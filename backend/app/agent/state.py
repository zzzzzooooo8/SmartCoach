from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    user_id: str
    conversation_id: str
    user_message: str
    user_message_id: str
    context: dict[str, Any]
    extraction: dict[str, Any]
    action_plan: list[str]
    operation_notes: list[str]
    knowledge_sources: list[dict[str, Any]]
    reply: str
    errors: list[str]
