import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.context import ContextManager
from app.agent.graph import invoke_agent
from app.database import database
from app.domain import build_weight_loss_plan


def main() -> None:
    user_id = "automated-smoke-user"
    database.reset_user(user_id)
    try:
        profile = database.upsert_profile(
            user_id,
            {
                "gender": "male",
                "age": 30,
                "height_cm": 175,
                "current_weight_kg": 80,
                "target_weight_kg": 70,
                "activity_level": "sedentary",
                "dietary_restrictions": [],
                "health_notes": [],
            },
        )
        database.create_plan(user_id, build_weight_loss_plan(profile))
        text = "我中午吃了200克苹果，晚上跑了30分钟，膝盖还有点疼"
        message = database.add_message(user_id, "main", "user", text)
        result = invoke_agent(user_id, "main", text, message["id"])
        database.add_message(user_id, "main", "assistant", result["reply"])
        context = ContextManager(database).build(user_id, "main")
        print("动作：", result.get("action_plan"))
        print("今日：", context["today"])
        print("记忆：", [item["content"] for item in context["memories"]])
        print("回复：", result["reply"])
        if "record_diet" not in result.get("action_plan", []):
            raise RuntimeError("饮食记录动作未触发")
        if "record_exercise" not in result.get("action_plan", []):
            raise RuntimeError("运动记录动作未触发")
        if context["today"]["burn"] != 0:
            raise RuntimeError("运动强度未明确时不应计入消耗")
        if not context["memories"]:
            raise RuntimeError("短期记忆未保存")

        follow_up = "是慢跑"
        follow_up_message = database.add_message(user_id, "main", "user", follow_up)
        follow_up_result = invoke_agent(
            user_id, "main", follow_up, follow_up_message["id"]
        )
        database.add_message(
            user_id, "main", "assistant", follow_up_result["reply"]
        )
        updated_context = ContextManager(database).build(user_id, "main")
        print("补充后今日：", updated_context["today"])
        print("补充后回复：", follow_up_result["reply"])
        if updated_context["today"]["burn"] <= 0:
            raise RuntimeError("补充运动强度后未完成待补充记录")
    finally:
        database.reset_user(user_id)


if __name__ == "__main__":
    main()
