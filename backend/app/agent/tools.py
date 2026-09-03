import re
from typing import Any

from app.database import Database
from app.rag import KnowledgeBase, SearchResult


class AgentTools:
    def __init__(self, database: Database, knowledge: KnowledgeBase) -> None:
        self.database = database
        self.knowledge = knowledge

    @staticmethod
    def source_payload(results: list[SearchResult]) -> list[dict[str, Any]]:
        return [
            {
                "name": item.source_name,
                "category": item.category,
                "score": item.score,
                "excerpt": item.content[:240],
            }
            for item in results
        ]

    @staticmethod
    def _food_calories_per_100g(food_name: str, results: list[SearchResult]) -> float | None:
        escaped = re.escape(food_name)
        patterns = [
            rf"{escaped}\s*[；,，:：]\s*(\d+(?:\.\d+)?)\s*/\s*100",
            rf"{escaped}\s*[；,，:：]\s*(\d+(?:\.\d+)?)",
        ]
        for result in results:
            for pattern in patterns:
                match = re.search(pattern, result.content)
                if match:
                    value = float(match.group(1))
                    if 0 <= value <= 1000:
                        return value
        return None

    @staticmethod
    def _met_from_results(results: list[SearchResult]) -> float | None:
        for result in results:
            match = re.search(r"\b\d{5}\s+(\d+(?:\.\d+)?)\b", result.content)
            if match:
                value = float(match.group(1))
                if 0 < value <= 25:
                    return value
        return None

    def record_diet(
        self,
        user_id: str,
        source_message_id: str,
        event: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        results = self.knowledge.search(f"{event['food_name']} 热量", category="food", limit=4)
        calories_per_100g = self._food_calories_per_100g(event["food_name"], results)
        amount = event.get("amount")
        unit = event.get("unit")
        calories = None
        grams = None
        if amount is not None and unit in ("克", "g"):
            grams = float(amount)
        elif amount is not None and unit in ("千克", "公斤", "kg"):
            grams = float(amount) * 1000
        if calories_per_100g is not None and grams is not None:
            calories = round(calories_per_100g * grams / 100, 2)

        needs_confirmation = bool(event.get("needs_confirmation")) or calories is None
        if event.get("pending_record_id") and not needs_confirmation:
            record = self.database.resolve_diet_record(
                user_id,
                event["pending_record_id"],
                float(amount),
                str(unit),
                float(calories),
            ) or {}
        else:
            record = self.database.add_diet_record(
                user_id,
                {
                    "food_name": event["food_name"],
                    "amount": amount,
                    "unit": unit,
                    "calories": calories,
                    "status": "pending" if needs_confirmation else "confirmed",
                    "source_message_id": source_message_id,
                },
            )
        if record["status"] == "confirmed":
            note = f"已记录饮食：{event['food_name']}，约 {calories} 千卡。"
        else:
            note = f"已暂存待补充饮食：{event['food_name']}；需要确认克数或可靠热量后才计入今日摄入。"
        return note, self.source_payload(results)

    def record_exercise(
        self,
        user_id: str,
        source_message_id: str,
        event: dict[str, Any],
        profile: dict[str, Any] | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        exercise_query = " ".join(
            part for part in (event["exercise_name"], event.get("intensity")) if part
        )
        results = self.knowledge.search(exercise_query, category="exercise", limit=4)
        met = self._met_from_results(results)
        duration = event.get("duration_minutes")
        weight = float(profile["current_weight_kg"]) if profile else None
        calories = None
        if met and duration and weight:
            calories = round(met * 3.5 * weight / 200 * float(duration), 2)
        intensity_sensitive = event["exercise_name"] in {
            "跑步", "步行", "骑车", "游泳", "力量训练"
        }
        needs_confirmation = (
            bool(event.get("needs_confirmation"))
            or calories is None
            or (intensity_sensitive and not event.get("intensity"))
        )
        if event.get("pending_record_id") and not needs_confirmation:
            record = self.database.resolve_exercise_record(
                user_id,
                event["pending_record_id"],
                str(event["intensity"]),
                float(met),
                float(calories),
            ) or {}
        else:
            record = self.database.add_exercise_record(
                user_id,
                {
                    "exercise_name": event["exercise_name"],
                    "duration_minutes": duration,
                    "distance_km": event.get("distance_km"),
                    "intensity": event.get("intensity"),
                    "met": met,
                    "calories_burned": calories,
                    "status": "pending" if needs_confirmation else "confirmed",
                    "source_message_id": source_message_id,
                },
            )
        if record["status"] == "confirmed":
            note = f"已记录运动：{event['exercise_name']}，约消耗 {calories} 千卡。"
        else:
            note = f"已暂存待补充运动：{event['exercise_name']}；需要确认时长、体重或运动强度。"
        return note, self.source_payload(results)

    def record_body(self, user_id: str, source_message_id: str, event: dict[str, Any]) -> str:
        self.database.add_body_record(
            user_id,
            {
                "weight_kg": event.get("weight_kg"),
                "sleep_hours": event.get("sleep_hours"),
                "note": event.get("note"),
                "source_message_id": source_message_id,
            },
        )
        details = []
        if event.get("weight_kg") is not None:
            details.append(f"体重 {event['weight_kg']} 千克")
        if event.get("sleep_hours") is not None:
            details.append(f"睡眠 {event['sleep_hours']} 小时")
        return f"已记录身体数据：{'，'.join(details) if details else '本次状态'}。"
