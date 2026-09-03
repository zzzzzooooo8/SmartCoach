import json
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.agent.context import ContextManager
from app.agent.facts import FactExtraction, FactExtractor, memory_to_record
from app.agent.state import AgentState
from app.agent.tools import AgentTools
from app.database import database
from app.rag import KnowledgeBase


load_dotenv()


knowledge_base = KnowledgeBase(database)
context_manager = ContextManager(database)
fact_extractor = FactExtractor()
agent_tools = AgentTools(database, knowledge_base)


def _build_chat_model() -> ChatOpenAI | None:
    model = os.getenv("CHAT_MODEL_ENDPOINT")
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    if not model or not api_key or not base_url:
        return None
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.5,
        timeout=45,
        max_retries=1,
    )


chat_model = _build_chat_model()


SYSTEM_PROMPT = """你是一名专业、严格但有同理心的减脂教练。
你会收到后端已经校验过的用户档案、计划、每日数据、记忆、执行结果和资料片段。
只把确认成功的记录当成今日数据；待补充记录必须明确向用户询问缺失信息。
涉及食物、运动和健康知识时，只依据提供的资料片段，不编造数值或来源。
短期健康限制处于待确认状态时，先询问是否恢复，再给高强度建议。
回复用简洁中文，开头直接回应，中间用短横线分点。不要输出隐藏标签、程序字段或内部推理。"""


def load_context_node(state: AgentState) -> dict[str, Any]:
    context = context_manager.build(state["user_id"], state["conversation_id"])
    return {"context": context, "errors": []}


def analyze_node(state: AgentState) -> dict[str, Any]:
    extraction = fact_extractor.extract(
        state["user_message"], state["context"].get("pending_records", [])
    )
    return {"extraction": extraction.model_dump()}


def plan_node(state: AgentState) -> dict[str, Any]:
    extraction = FactExtraction.model_validate(state["extraction"])
    actions: list[str] = []
    if extraction.diet_events:
        actions.append("record_diet")
    if extraction.exercise_events:
        actions.append("record_exercise")
    if extraction.body_events:
        actions.append("record_body")
    if extraction.memory_candidates:
        actions.append("save_memory")
    if extraction.needs_knowledge or "knowledge_query" in extraction.intents:
        actions.append("retrieve_knowledge")
    return {"action_plan": actions[:5]}


def execute_node(state: AgentState) -> dict[str, Any]:
    extraction = FactExtraction.model_validate(state["extraction"])
    notes: list[str] = []
    sources: list[dict[str, Any]] = []
    errors: list[str] = list(state.get("errors", []))
    profile = state["context"].get("profile")

    for action in state.get("action_plan", [])[:5]:
        try:
            if action == "record_diet":
                for event in extraction.diet_events:
                    if event.completed:
                        note, found_sources = agent_tools.record_diet(
                            state["user_id"], state["user_message_id"], event.model_dump()
                        )
                        notes.append(note)
                        sources.extend(found_sources)
            elif action == "record_exercise":
                for event in extraction.exercise_events:
                    if event.completed:
                        note, found_sources = agent_tools.record_exercise(
                            state["user_id"], state["user_message_id"], event.model_dump(), profile
                        )
                        notes.append(note)
                        sources.extend(found_sources)
            elif action == "record_body":
                for event in extraction.body_events:
                    notes.append(
                        agent_tools.record_body(
                            state["user_id"], state["user_message_id"], event.model_dump()
                        )
                    )
            elif action == "save_memory":
                for memory in extraction.memory_candidates:
                    saved = database.save_memory(
                        state["user_id"], memory_to_record(memory, state["user_message_id"])
                    )
                    status_text = "待确认" if saved["status"] == "pending_confirmation" else "已记住"
                    notes.append(f"{status_text}：{saved['content']}。")
            elif action == "retrieve_knowledge":
                results = knowledge_base.search(state["user_message"], limit=4)
                sources.extend(agent_tools.source_payload(results))
        except Exception as exc:
            errors.append(f"{action} 执行失败：{exc}")

    unique_sources: list[dict[str, Any]] = []
    seen = set()
    for source in sources:
        key = (source["name"], source["excerpt"])
        if key not in seen:
            seen.add(key)
            unique_sources.append(source)
    refreshed = context_manager.build(state["user_id"], state["conversation_id"])
    return {
        "operation_notes": notes,
        "knowledge_sources": unique_sources[:6],
        "context": refreshed,
        "errors": errors,
    }


def _fallback_reply(state: AgentState) -> str:
    notes = state.get("operation_notes", [])
    if notes:
        return "我已经处理了这次信息。\n\n" + "\n".join(f"- {note}" for note in notes)
    sources = state.get("knowledge_sources", [])
    if sources:
        return f"我找到了相关资料，但当前对话模型不可用。\n\n- {sources[0]['excerpt']}\n- 来源：{sources[0]['name']}"
    return "当前对话模型暂不可用；你的消息已经安全保存，请稍后重试。"


def respond_node(state: AgentState) -> dict[str, Any]:
    if not state["context"].get("profile"):
        return {"reply": "请先完成基础建档，我会据此生成第一版减脂计划，再开始记录和建议。"}
    if chat_model is None:
        return {"reply": _fallback_reply(state)}

    recent = state["context"].get("recent_messages", [])
    recent_text = "\n".join(f"{item['role']}：{item['content']}" for item in recent)
    sources_text = "\n\n".join(
        f"来源：{item['name']}\n{item['excerpt']}" for item in state.get("knowledge_sources", [])
    ) or "本轮未检索资料"
    prompt = "\n\n".join(
        [
            context_manager.format_for_prompt(state["context"]),
            f"【近期对话】\n{recent_text}",
            f"【本轮执行计划】\n{json.dumps(state.get('action_plan', []), ensure_ascii=False)}",
            f"【已执行结果】\n" + ("\n".join(state.get("operation_notes", [])) or "无数据变化"),
            f"【检索资料】\n{sources_text}",
            f"【用户当前消息】\n{state['user_message']}",
        ]
    )
    try:
        response = chat_model.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
        return {"reply": str(response.content).strip()}
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"回复生成失败：{exc}")
        return {"reply": _fallback_reply(state), "errors": errors}


builder = StateGraph(AgentState)
builder.add_node("load_context", load_context_node)
builder.add_node("analyze", analyze_node)
builder.add_node("plan", plan_node)
builder.add_node("execute", execute_node)
builder.add_node("respond", respond_node)
builder.add_edge(START, "load_context")
builder.add_edge("load_context", "analyze")
builder.add_edge("analyze", "plan")
builder.add_edge("plan", "execute")
builder.add_edge("execute", "respond")
builder.add_edge("respond", END)
app = builder.compile()


def invoke_agent(user_id: str, conversation_id: str, message: str, message_id: str) -> AgentState:
    return app.invoke(
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "user_message": message,
            "user_message_id": message_id,
        }
    )
