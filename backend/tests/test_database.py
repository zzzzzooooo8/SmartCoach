import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.domain import build_weight_loss_plan


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.user_id = "test-user"
        self.profile_data = {
            "gender": "male",
            "age": 30,
            "height_cm": 175,
            "current_weight_kg": 80,
            "target_weight_kg": 70,
            "activity_level": "sedentary",
            "dietary_restrictions": ["乳糖不耐受"],
            "health_notes": [],
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_schema_has_eleven_tables(self) -> None:
        rows = self.database.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        names = {row["name"] for row in rows}
        expected = {
            "users", "user_profiles", "weight_loss_plans", "diet_records",
            "exercise_records", "body_life_records", "chat_messages",
            "user_memories", "conversation_summaries", "knowledge_documents",
            "knowledge_chunks",
        }
        self.assertTrue(expected.issubset(names))
        self.assertIn("knowledge_chunks_fts", names)

    def test_profile_plan_and_version(self) -> None:
        profile = self.database.upsert_profile(self.user_id, self.profile_data)
        first = self.database.create_plan(
            self.user_id, build_weight_loss_plan(profile, 0.5)
        )
        second = self.database.create_plan(
            self.user_id, build_weight_loss_plan(profile, 0.4)
        )
        self.assertEqual(1, first["version"])
        self.assertEqual(2, second["version"])
        old = self.database.fetch_one(
            "SELECT status FROM weight_loss_plans WHERE id = ?", (first["id"],)
        )
        self.assertEqual("superseded", old["status"])

    def test_event_summary_and_soft_reset(self) -> None:
        profile = self.database.upsert_profile(self.user_id, self.profile_data)
        self.database.create_plan(self.user_id, build_weight_loss_plan(profile))
        self.database.add_diet_record(
            self.user_id,
            {"food_name": "苹果", "amount": 1, "unit": "个", "calories": 95, "protein_g": 0.5},
        )
        self.database.add_exercise_record(
            self.user_id,
            {"exercise_name": "快走", "duration_minutes": 30, "calories_burned": 150},
        )
        summary = self.database.daily_summary(self.user_id)
        self.assertEqual(95, summary["intake"])
        self.assertEqual(150, summary["burn"])
        self.database.reset_daily_records(self.user_id)
        summary = self.database.daily_summary(self.user_id)
        self.assertEqual(0, summary["intake"])
        self.assertEqual(0, summary["burn"])


if __name__ == "__main__":
    unittest.main()
