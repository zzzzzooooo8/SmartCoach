import os
import re
import warnings
from datetime import datetime, timedelta, timezone
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


load_dotenv()


Intent = Literal[
    "record_diet",
    "record_exercise",
    "record_body",
    "update_memory",
    "change_plan",
    "knowledge_query",
    "general_chat",
]


class DietFact(BaseModel):
    food_name: str
    amount: float | None = None
    unit: str | None = None
    completed: bool = True
    needs_confirmation: bool = False
    pending_record_id: str | None = None


class ExerciseFact(BaseModel):
    exercise_name: str
    duration_minutes: float | None = None
    distance_km: float | None = None
    intensity: str | None = None
    completed: bool = True
    needs_confirmation: bool = False
    pending_record_id: str | None = None


class BodyFact(BaseModel):
    weight_kg: float | None = None
    sleep_hours: float | None = None
    note: str | None = None


class MemoryFact(BaseModel):
    category: Literal["dietary_constraint", "preference", "health_constraint", "lifestyle", "goal"]
    content: str
    duration_type: Literal["long_term", "short_term"]
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    confidence: float = Field(default=1, ge=0, le=1)
    needs_confirmation: bool = False


class FactExtraction(BaseModel):
    intents: list[Intent] = Field(default_factory=lambda: ["general_chat"])
    diet_events: list[DietFact] = Field(default_factory=list)
    exercise_events: list[ExerciseFact] = Field(default_factory=list)
    body_events: list[BodyFact] = Field(default_factory=list)
    memory_candidates: list[MemoryFact] = Field(default_factory=list)
    needs_knowledge: bool = False
    clarification: str | None = None


EXTRACTION_PROMPT = """你是减脂应用的信息提取器。只提取用户明确表达的事实，不诊断、不计算热量。
区分已经发生、将来计划、普通查询和否定表达。只有已经吃过或完成的运动才能标为 completed。
饮食或运动缺少关键份量、时长时标记 needs_confirmation。
稳定忌口和偏好属于长期记忆；伤痛、感冒、出差等属于有期限的短期记忆。
模糊健康信息必须标记需要确认。返回规定的数据结构，不要生成聊天回复。"""


class FactExtractor:
    def __init__(self, use_model: bool = True) -> None:
        model = os.getenv("CHAT_MODEL_ENDPOINT")
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        self.model = None
        if use_model and model and api_key and base_url:
            self.model = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=0,
                timeout=30,
                max_retries=1,
            ).with_structured_output(FactExtraction)

    def extract(self, message: str, pending_records: list[dict[str, object]] | None = None) -> FactExtraction:
        pending_records = pending_records or []
        if not self._needs_extraction(message):
            resolved = self._fallback_pending_resolution(message, pending_records)
            if resolved is not None:
                return resolved
            return FactExtraction(
                intents=["knowledge_query"] if self._is_query(message) else ["general_chat"],
                needs_knowledge=self._is_knowledge_query(message),
            )
        if self.model is not None:
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="Pydantic serializer warnings.*",
                        category=UserWarning,
                    )
                    result = self.model.invoke(
                        [
                            SystemMessage(content=EXTRACTION_PROMPT),
                            HumanMessage(content=f"待补充记录：{pending_records}\n\n用户消息：{message}"),
                        ]
                    )
                if isinstance(result, FactExtraction):
                    return result
            except Exception:
                pass
        return self._fallback_extract(message)

    @staticmethod
    def _fallback_pending_resolution(
        message: str, pending_records: list[dict[str, object]]
    ) -> FactExtraction | None:
        pending_diet = next((item for item in pending_records if item.get("record_type") == "diet"), None)
        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*(克|千克|公斤|g|kg)", message, re.IGNORECASE)
        if pending_diet and amount_match:
            return FactExtraction(
                intents=["record_diet"],
                diet_events=[
                    DietFact(
                        food_name=str(pending_diet["name"]),
                        amount=float(amount_match.group(1)),
                        unit=amount_match.group(2),
                        pending_record_id=str(pending_diet["id"]),
                    )
                ],
            )
        pending_exercise = next((item for item in pending_records if item.get("record_type") == "exercise"), None)
        intensity_match = re.search(r"(慢跑|快跑|低强度|中等强度|中强度|高强度|轻松|剧烈)", message)
        if pending_exercise and intensity_match:
            return FactExtraction(
                intents=["record_exercise"],
                exercise_events=[
                    ExerciseFact(
                        exercise_name=str(pending_exercise["name"]),
                        duration_minutes=float(pending_exercise["duration_minutes"]) if pending_exercise.get("duration_minutes") else None,
                        intensity=intensity_match.group(1),
                        pending_record_id=str(pending_exercise["id"]),
                    )
                ],
            )
        return None

    @staticmethod
    def _is_query(message: str) -> bool:
        return any(token in message for token in ("吗", "多少", "怎么", "什么", "推荐", "能不能", "可以吗", "？", "?"))

    @staticmethod
    def _is_knowledge_query(message: str) -> bool:
        return any(token in message for token in ("热量", "大卡", "食谱", "吃什么", "运动", "消耗", "减脂", "健康", "营养"))

    def _needs_extraction(self, message: str) -> bool:
        tokens = (
            "吃了", "喝了", "刚吃", "刚喝", "跑了", "走了", "骑了", "游了",
            "练了", "做了", "体重", "公斤", "千克", "斤", "不耐受", "过敏",
            "不吃", "素食", "疼", "痛", "感冒", "不舒服", "目标", "早餐",
            "午餐", "晚餐", "夜宵", "完成了", "分钟", "小时", "我喜欢",
        )
        return any(token in message for token in tokens)

    def _fallback_extract(self, message: str) -> FactExtraction:
        result = FactExtraction(intents=[])
        is_question = self._is_query(message)
        is_planned = any(token in message for token in ("想吃", "准备吃", "打算吃", "想跑", "准备跑", "打算运动"))
        is_negative = any(token in message for token in ("没吃", "没有吃", "没运动", "没有运动", "没跑"))

        food_match = re.search(r"(?:吃了|喝了|刚吃了?|刚喝了?)([^，。！？]+)", message)
        if food_match and not is_planned and not is_negative:
            phrase = food_match.group(1).strip()
            amount_match = re.search(r"(半|\d+(?:\.\d+)?)\s*(碗|个|份|克|千克|公斤|杯|瓶|罐|片|块|只|串)", phrase)
            amount = None
            unit = None
            if amount_match:
                amount = 0.5 if amount_match.group(1) == "半" else float(amount_match.group(1))
                unit = amount_match.group(2)
            food_name = re.sub(r"(半|\d+(?:\.\d+)?)\s*(碗|个|份|克|千克|公斤|杯|瓶|罐|片|块|只|串)", "", phrase).strip()
            result.intents.append("record_diet")
            result.diet_events.append(
                DietFact(food_name=food_name or phrase, amount=amount, unit=unit, needs_confirmation=amount is None)
            )

        exercise_map = {
            "跑": "跑步", "快走": "快走", "走": "步行", "骑": "骑车",
            "游": "游泳", "跳绳": "跳绳", "力量": "力量训练", "瑜伽": "瑜伽",
        }
        exercise_name = next((name for key, name in exercise_map.items() if key in message), None)
        completed_exercise = any(token in message for token in ("跑了", "走了", "骑了", "游了", "练了", "做了", "刚跑完", "刚练完"))
        if exercise_name and completed_exercise and not is_planned and not is_negative:
            duration_match = re.search(r"(\d+(?:\.\d+)?)\s*(分钟|小时)", message)
            duration = None
            if duration_match:
                duration = float(duration_match.group(1)) * (60 if duration_match.group(2) == "小时" else 1)
            distance_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:公里|千米|km)", message, re.IGNORECASE)
            result.intents.append("record_exercise")
            result.exercise_events.append(
                ExerciseFact(
                    exercise_name=exercise_name,
                    duration_minutes=duration,
                    distance_km=float(distance_match.group(1)) if distance_match else None,
                    needs_confirmation=duration is None and distance_match is None,
                )
            )

        weight_match = re.search(r"(?:体重|称了?|现在)(?:是|有)?\s*(\d+(?:\.\d+)?)\s*(公斤|千克|kg|斤)", message, re.IGNORECASE)
        if weight_match:
            weight = float(weight_match.group(1))
            if weight_match.group(2) == "斤":
                weight /= 2
            result.intents.append("record_body")
            result.body_events.append(BodyFact(weight_kg=weight))

        long_term_patterns = (
            (r"乳糖不耐受", "dietary_constraint", "乳糖不耐受"),
            (r"对([^，。]+)过敏", "dietary_constraint", None),
            (r"(?:我是|吃)素食", "dietary_constraint", "采用素食饮食"),
            (r"不吃([^，。]+)", "preference", None),
        )
        for pattern, category, fixed_content in long_term_patterns:
            match = re.search(pattern, message)
            if match:
                content = fixed_content or match.group(0)
                result.intents.append("update_memory")
                result.memory_candidates.append(
                    MemoryFact(category=category, content=content, duration_type="long_term")
                )

        health_match = re.search(r"([^，。]{0,8}(?:膝盖|腰|脚踝|肩膀)[^，。]{0,8}(?:疼|痛|不舒服)|感冒(?:了)?|身体不舒服)", message)
        if health_match:
            result.intents.append("update_memory")
            result.memory_candidates.append(
                MemoryFact(
                    category="health_constraint",
                    content=health_match.group(0),
                    duration_type="short_term",
                    expires_in_days=7,
                    confidence=0.9,
                )
            )

        result.needs_knowledge = self._is_knowledge_query(message)
        if result.needs_knowledge and "knowledge_query" not in result.intents:
            result.intents.append("knowledge_query")
        if not result.intents:
            result.intents = ["knowledge_query" if is_question else "general_chat"]
        return result


def memory_to_record(memory: MemoryFact, source_message_id: str) -> dict[str, object]:
    expires_at = None
    if memory.duration_type == "short_term":
        days = memory.expires_in_days or 7
        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    return {
        "category": memory.category,
        "content": memory.content,
        "duration_type": memory.duration_type,
        "expires_at": expires_at,
        "confidence": memory.confidence,
        "is_confirmed": not memory.needs_confirmation,
        "status": "pending_confirmation" if memory.needs_confirmation else "active",
        "source_message_id": source_message_id,
    }
