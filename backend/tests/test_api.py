import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agent.context import ContextManager
from app.database import Database
from app.main import app


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "api.db")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_onboarding_bootstrap_and_chat_contract(self) -> None:
        user_id = "api-user"
        manager = ContextManager(self.database)
        with patch("app.main.database", self.database):
            before = self.client.get("/api/bootstrap", params={"user_id": user_id})
            self.assertTrue(before.json()["needs_onboarding"])
            saved = self.client.post(
                "/api/profile",
                json={
                    "user_id": user_id,
                    "gender": "male",
                    "age": 30,
                    "height_cm": 175,
                    "current_weight_kg": 80,
                    "target_weight_kg": 70,
                    "activity_level": "sedentary",
                    "target_loss_speed": 0.5,
                    "dietary_restrictions": [],
                    "health_notes": [],
                },
            )
            self.assertEqual(200, saved.status_code)
            self.assertIsNotNone(saved.json()["plan"]["daily_calorie_target"])

        fake_result = {
            "reply": "测试回复",
            "knowledge_sources": [],
            "action_plan": ["general_chat"],
            "errors": [],
        }
        with (
            patch("app.main.database", self.database),
            patch("app.main.context_manager", manager),
            patch("app.main.invoke_agent", return_value=fake_result),
        ):
            response = self.client.post(
                "/api/chat",
                json={"user_id": user_id, "conversation_id": "main", "message": "你好"},
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual("测试回复", response.json()["reply"])
        self.assertEqual(2, len(self.database.list_messages(user_id, "main")))


if __name__ == "__main__":
    unittest.main()
