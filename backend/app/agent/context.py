import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.database import Database


load_dotenv()


class ContextManager:
    def __init__(self, database: Database) -> None:
        self.database = database
        model = os.getenv("CHAT_MODEL_ENDPOINT")
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        self.summary_model = None
        if model and api_key and base_url:
            self.summary_model = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=0,
                timeout=30,
                max_retries=1,
            )

    def build(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        return {
            "profile": self.database.get_profile(user_id),
            "plan": self.database.get_active_plan(user_id),
            "today": self.database.daily_summary(user_id),
            "memories": self.database.list_active_memories(user_id),
            "pending_records": self.database.list_pending_records(user_id),
            "summary": self.database.get_summary(user_id, conversation_id),
            "recent_messages": self.database.list_messages(user_id, conversation_id, limit=10),
        }

    @staticmethod
    def format_for_prompt(context: dict[str, Any]) -> str:
        profile = context.get("profile") or {}
        plan = context.get("plan") or {}
        today = context.get("today") or {}
        memories = context.get("memories") or []
        summary = context.get("summary") or {}
        pending = context.get("pending_records") or []
        memory_lines = [
            f"- {item['content']}（{item['status']}，{item['duration_type']}）"
            for item in memories
        ]
        return "\n".join(
            [
                "【用户档案】",
                f"性别：{profile.get('gender', '未知')}；年龄：{profile.get('age', '未知')}；身高：{profile.get('height_cm', '未知')}cm；当前体重：{profile.get('current_weight_kg', '未知')}kg；目标体重：{profile.get('target_weight_kg', '未知')}kg；活动量：{profile.get('activity_level', '未知')}；饮食限制：{profile.get('dietary_restrictions', [])}；健康提醒：{profile.get('health_notes', [])}",
                "【当前计划】",
                f"每日热量目标：{plan.get('daily_calorie_target', '未建立')}；蛋白质目标：{plan.get('daily_protein_target', '未建立')}g",
                "【今日数据】",
                f"摄入：{today.get('intake', 0)}kcal；蛋白质：{today.get('protein', 0)}g；运动消耗：{today.get('burn', 0)}kcal",
                "【有效记忆】",
                "\n".join(memory_lines) if memory_lines else "无",
                "【待补充记录】",
                "\n".join(f"- {item['record_type']}：{item['name']}（编号 {item['id']}）" for item in pending) if pending else "无",
                "【早期对话摘要】",
                summary.get("content", "无"),
            ]
        )

    def maybe_update_summary(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        messages = self.database.list_messages(user_id, conversation_id, limit=200)
        existing = self.database.get_summary(user_id, conversation_id)
        previous_count = int(existing["message_count"]) if existing else 0
        if len(messages) < 20 or len(messages) - previous_count < 10:
            return existing
        older = messages[:-10]
        source = "\n".join(f"{item['role']}：{item['content']}" for item in older)
        summary = self._summarize(source, existing["content"] if existing else "")
        return self.database.upsert_summary(
            user_id,
            conversation_id,
            summary,
            older[0]["created_at"] if older else None,
            older[-1]["created_at"] if older else None,
            len(messages),
        )

    def _summarize(self, source: str, old_summary: str) -> str:
        if self.summary_model is not None:
            try:
                response = self.summary_model.invoke(
                    [
                        SystemMessage(content="将减脂对话压缩为简短摘要，只保留用户事实、偏好、变化、未完成事项和已确认结论。不要猜测。"),
                        HumanMessage(content=f"旧摘要：{old_summary or '无'}\n\n待总结对话：\n{source}"),
                    ]
                )
                return str(response.content).strip()
            except Exception:
                pass
        compact = source.replace("\n\n", "\n")
        return compact[-1800:]
