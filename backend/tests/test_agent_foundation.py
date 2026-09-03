import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.agent import graph
from app.agent.context import ContextManager
from app.agent.facts import FactExtractor, memory_to_record
from app.agent.tools import AgentTools
from app.database import Database
from app.domain import build_weight_loss_plan
from app.rag import KnowledgeBase
from app.vector_store import ChromaVectorStore


class NoEmbedding:
    model_name = "test-no-embedding"
    available = False

    def embed_query(self, text: str):
        return None


class NoRerank:
    available = False

    def rerank(self, query, candidates, top_n):
        return None


class EmptyVectorStore:
    collection_name = "test-empty"
    available = True
    path = Path("test-empty")

    def count(self):
        return 0

    def delete_by_source(self, source):
        return None

    def ids_by_source(self, source):
        return []

    def delete_ids(self, ids):
        return None

    def upsert(self, items):
        return len(items)

    def contains_ids(self, ids):
        return 0

    def query(self, query_vector, category=None, limit=30):
        return []


class StaticEmbedding:
    model_name = "test-qwen3-embedding"
    available = True

    @staticmethod
    def _vector(text):
        return [1.0, 0.0] if "苹果" in text else [0.0, 1.0]

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


class AgentFoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fact_extraction_distinguishes_record_and_query(self) -> None:
        extractor = FactExtractor(use_model=False)
        recorded = extractor.extract("我中午吃了2个苹果，晚上跑了30分钟")
        queried = extractor.extract("苹果有多少热量？")
        planned = extractor.extract("我晚上想吃苹果")
        self.assertIn("record_diet", recorded.intents)
        self.assertIn("record_exercise", recorded.intents)
        self.assertEqual(2, recorded.diet_events[0].amount)
        self.assertEqual(30, recorded.exercise_events[0].duration_minutes)
        self.assertEqual([], queried.diet_events)
        self.assertTrue(queried.needs_knowledge)
        self.assertEqual([], planned.diet_events)

    def test_memory_expiry_and_context(self) -> None:
        self.database.ensure_user("u1")
        extraction = FactExtractor(use_model=False).extract("我的膝盖还有点疼")
        memory = memory_to_record(extraction.memory_candidates[0], "message-1")
        memory["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.database.save_memory("u1", memory)
        context = ContextManager(self.database).build("u1", "main")
        self.assertEqual("pending_confirmation", context["memories"][0]["status"])
        self.assertIn("膝盖", ContextManager.format_for_prompt(context))

    def test_knowledge_import_and_lexical_search(self) -> None:
        data_dir = Path(self.temp_dir.name) / "knowledge"
        data_dir.mkdir()
        (data_dir / "calorie-of-food.csv").write_text(
            "食品名称,热量(千卡)/100克\n苹果,52\n炸薯片,612\n", encoding="utf-8"
        )
        (data_dir / "optimize-the-dietary-structure.txt").write_text(
            "科学减脂要保持合理热量缺口，并保证蛋白质摄入。", encoding="utf-8"
        )
        knowledge = KnowledgeBase(
            self.database, NoEmbedding(), NoRerank(), EmptyVectorStore()
        )
        result = knowledge.rebuild(data_dir, with_embeddings=False)
        hits = knowledge.search("苹果热量", limit=2)
        self.assertEqual(2, result["documents"])
        self.assertGreaterEqual(result["chunks"], 3)
        self.assertTrue(hits)
        self.assertIn("苹果", hits[0].content)

    def test_agent_graph_records_confirmed_food(self) -> None:
        user_id = "graph-user"
        profile_data = {
            "gender": "male", "age": 30, "height_cm": 175,
            "current_weight_kg": 80, "target_weight_kg": 70,
            "activity_level": "sedentary", "dietary_restrictions": [],
            "health_notes": [],
        }
        profile = self.database.upsert_profile(user_id, profile_data)
        self.database.create_plan(user_id, build_weight_loss_plan(profile))
        message = self.database.add_message(user_id, "main", "user", "我吃了200克苹果")

        data_dir = Path(self.temp_dir.name) / "graph-knowledge"
        data_dir.mkdir()
        (data_dir / "calorie-of-food.csv").write_text(
            "食品名称,热量(千卡)/100克\n苹果,52/100\n", encoding="utf-8"
        )
        knowledge = KnowledgeBase(
            self.database, NoEmbedding(), NoRerank(), EmptyVectorStore()
        )
        knowledge.rebuild(data_dir, with_embeddings=False)
        manager = ContextManager(self.database)
        tools = AgentTools(self.database, knowledge)

        with patch.multiple(
            graph,
            database=self.database,
            context_manager=manager,
            fact_extractor=FactExtractor(use_model=False),
            knowledge_base=knowledge,
            agent_tools=tools,
            chat_model=None,
        ):
            result = graph.invoke_agent(user_id, "main", "我吃了200克苹果", message["id"])

        self.assertIn("record_diet", result["action_plan"])
        self.assertEqual(104, self.database.daily_summary(user_id)["intake"])
        self.assertIn("已记录饮食", result["reply"])

    def test_pending_exercise_can_be_completed_by_follow_up(self) -> None:
        user_id = "pending-user"
        profile = self.database.upsert_profile(
            user_id,
            {
                "gender": "male", "age": 30, "height_cm": 175,
                "current_weight_kg": 80, "target_weight_kg": 70,
                "activity_level": "sedentary", "dietary_restrictions": [],
                "health_notes": [],
            },
        )
        pending = self.database.add_exercise_record(
            user_id,
            {"exercise_name": "跑步", "duration_minutes": 30, "status": "pending"},
        )
        data_dir = Path(self.temp_dir.name) / "exercise-knowledge"
        data_dir.mkdir()
        (data_dir / "chinese-2011-compendium-of-physical-activities-v1.1.csv").write_text(
            "跑步：慢跑\n12001 8.3\nrunning, jogging\n", encoding="utf-8"
        )
        knowledge = KnowledgeBase(
            self.database, NoEmbedding(), NoRerank(), EmptyVectorStore()
        )
        knowledge.rebuild(data_dir, with_embeddings=False)
        extracted = FactExtractor(use_model=False).extract(
            "是慢跑", self.database.list_pending_records(user_id)
        )
        event = extracted.exercise_events[0].model_dump()
        note, _ = AgentTools(self.database, knowledge).record_exercise(
            user_id, "follow-up", event, profile
        )
        resolved = self.database.fetch_one(
            "SELECT * FROM exercise_records WHERE id = ?", (pending["id"],)
        )
        self.assertEqual("confirmed", resolved["status"])
        self.assertGreater(resolved["calories_burned"], 0)
        self.assertIn("已记录运动", note)

    def test_vectors_are_written_to_chroma_not_sqlite(self) -> None:
        data_dir = Path(self.temp_dir.name) / "chroma-knowledge"
        data_dir.mkdir()
        (data_dir / "calorie-of-food.csv").write_text(
            "食品名称,热量(千卡)/100克\n苹果,52\n炸薯片,612\n", encoding="utf-8"
        )
        vector_store = ChromaVectorStore(
            Path(self.temp_dir.name) / "chroma", "fitness-test"
        )
        knowledge = KnowledgeBase(
            self.database, StaticEmbedding(), NoRerank(), vector_store
        )
        try:
            result = knowledge.rebuild(data_dir, with_embeddings=True)
            columns = {
                row["name"] for row in self.database.fetch_all("PRAGMA table_info(knowledge_chunks)")
            }

            self.assertEqual(result["chunks"], vector_store.count())
            self.assertNotIn("embedding", columns)
            self.assertNotIn("embedding_model", columns)
            self.assertIn("苹果", knowledge.search("苹果热量", category="food")[0].content)
        finally:
            vector_store.close()


if __name__ == "__main__":
    unittest.main()
