import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from dotenv import load_dotenv


load_dotenv()

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _keyword_terms(text: str) -> list[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
    bigrams = {
        "".join(chinese[index:index + 2])
        for index in range(max(0, len(chinese) - 1))
    }
    words = set(re.findall(r"[a-z0-9]+", normalized))
    return sorted(bigrams | words)


def _fts_query(text: str) -> str:
    return " OR ".join(f'"{term}"' for term in _keyword_terms(text))


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    gender TEXT NOT NULL,
    age INTEGER NOT NULL,
    height_cm REAL NOT NULL,
    current_weight_kg REAL NOT NULL,
    target_weight_kg REAL,
    activity_level TEXT NOT NULL,
    dietary_restrictions TEXT NOT NULL DEFAULT '[]',
    health_notes TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weight_loss_plans (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    bmr REAL NOT NULL,
    tdee REAL NOT NULL,
    daily_calorie_target REAL NOT NULL,
    daily_protein_target REAL NOT NULL,
    target_loss_speed REAL NOT NULL,
    training_advice TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    UNIQUE(user_id, version)
);

CREATE TABLE IF NOT EXISTS diet_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_date TEXT NOT NULL,
    record_time TEXT,
    food_name TEXT NOT NULL,
    amount REAL,
    unit TEXT,
    calories REAL,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    source_message_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exercise_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_date TEXT NOT NULL,
    record_time TEXT,
    exercise_name TEXT NOT NULL,
    duration_minutes REAL,
    distance_km REAL,
    intensity TEXT,
    met REAL,
    calories_burned REAL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    source_message_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS body_life_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_date TEXT NOT NULL,
    weight_kg REAL,
    waist_cm REAL,
    steps INTEGER,
    sleep_hours REAL,
    fatigue_level INTEGER,
    note TEXT,
    source_message_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    duration_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    valid_from TEXT NOT NULL,
    expires_at TEXT,
    confidence REAL NOT NULL DEFAULT 1,
    is_confirmed INTEGER NOT NULL DEFAULT 1,
    source_message_id TEXT,
    last_confirmed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL,
    content TEXT NOT NULL,
    range_start TEXT,
    range_end TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, conversation_id)
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL,
    version TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source, version)
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    category TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    suitable_for TEXT NOT NULL DEFAULT '[]',
    restrictions TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_plans_user_status ON weight_loss_plans(user_id, status);
CREATE INDEX IF NOT EXISTS idx_diet_user_date ON diet_records(user_id, record_date, status);
CREATE INDEX IF NOT EXISTS idx_exercise_user_date ON exercise_records(user_id, record_date, status);
CREATE INDEX IF NOT EXISTS idx_body_user_date ON body_life_records(user_id, record_date);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON chat_messages(user_id, conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memories_user_status ON user_memories(user_id, status, expires_at);
CREATE INDEX IF NOT EXISTS idx_chunks_category ON knowledge_chunks(category, enabled);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    category UNINDEXED,
    terms
);
"""


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        configured = path or os.getenv("SQLITE_DATABASE_PATH")
        self.path = Path(configured) if configured else Path(__file__).resolve().parent / "data" / "fitness_agent.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._rebuild_knowledge_fts(connection)

    @staticmethod
    def _rebuild_knowledge_fts(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM knowledge_chunks_fts")
        rows = connection.execute(
            "SELECT id, category, content FROM knowledge_chunks WHERE enabled = 1"
        ).fetchall()
        connection.executemany(
            "INSERT INTO knowledge_chunks_fts (chunk_id, category, terms) VALUES (?, ?, ?)",
            [
                (row["id"], row["category"], " ".join(_keyword_terms(row["content"])))
                for row in rows
            ],
        )

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        with self.connect() as connection:
            connection.execute(sql, parameters)

    def fetch_one(self, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(sql, parameters).fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            return [dict(row) for row in rows]

    def ensure_user(self, user_id: str) -> None:
        self.execute(
            "INSERT OR IGNORE INTO users (id, created_at, status) VALUES (?, ?, 'active')",
            (user_id, utc_now()),
        )

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        row = self.fetch_one("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
        if row:
            row["dietary_restrictions"] = json.loads(row["dietary_restrictions"])
            row["health_notes"] = json.loads(row["health_notes"])
        return row

    def upsert_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        self.ensure_user(user_id)
        now = utc_now()
        existing = self.get_profile(user_id)
        profile_id = existing["id"] if existing else new_id("profile")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_profiles (
                    id, user_id, gender, age, height_cm, current_weight_kg,
                    target_weight_kg, activity_level, dietary_restrictions,
                    health_notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    gender = excluded.gender,
                    age = excluded.age,
                    height_cm = excluded.height_cm,
                    current_weight_kg = excluded.current_weight_kg,
                    target_weight_kg = excluded.target_weight_kg,
                    activity_level = excluded.activity_level,
                    dietary_restrictions = excluded.dietary_restrictions,
                    health_notes = excluded.health_notes,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_id,
                    user_id,
                    profile["gender"],
                    profile["age"],
                    profile["height_cm"],
                    profile["current_weight_kg"],
                    profile.get("target_weight_kg"),
                    profile["activity_level"],
                    json.dumps(profile.get("dietary_restrictions", []), ensure_ascii=False),
                    json.dumps(profile.get("health_notes", []), ensure_ascii=False),
                    existing["created_at"] if existing else now,
                    now,
                ),
            )
        return self.get_profile(user_id) or {}

    def create_plan(self, user_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        self.ensure_user(user_id)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM weight_loss_plans WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            version = int(row["version"]) + 1
            connection.execute(
                "UPDATE weight_loss_plans SET status = 'superseded' WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            plan_id = new_id("plan")
            connection.execute(
                """
                INSERT INTO weight_loss_plans (
                    id, user_id, version, start_date, end_date, bmr, tdee,
                    daily_calorie_target, daily_protein_target,
                    target_loss_speed, training_advice, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    plan_id,
                    user_id,
                    version,
                    plan.get("start_date", date.today().isoformat()),
                    plan.get("end_date"),
                    plan["bmr"],
                    plan["tdee"],
                    plan["daily_calorie_target"],
                    plan["daily_protein_target"],
                    plan["target_loss_speed"],
                    plan.get("training_advice", ""),
                    utc_now(),
                ),
            )
        return self.get_active_plan(user_id) or {}

    def get_active_plan(self, user_id: str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM weight_loss_plans WHERE user_id = ? AND status = 'active' ORDER BY version DESC LIMIT 1",
            (user_id,),
        )

    def add_message(self, user_id: str, conversation_id: str, role: str, content: str) -> dict[str, Any]:
        self.ensure_user(user_id)
        message = {
            "id": new_id("message"),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": utc_now(),
        }
        self.execute(
            "INSERT INTO chat_messages (id, user_id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            tuple(message.values()),
        )
        return message

    def list_messages(self, user_id: str, conversation_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.fetch_all(
            """
            SELECT * FROM (
                SELECT * FROM chat_messages
                WHERE user_id = ? AND conversation_id = ?
                ORDER BY created_at DESC LIMIT ?
            ) ORDER BY created_at ASC
            """,
            (user_id, conversation_id, limit),
        )
        return rows

    def add_diet_record(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        self.ensure_user(user_id)
        item = {
            "id": new_id("diet"), "user_id": user_id,
            "record_date": record.get("record_date", date.today().isoformat()),
            "record_time": record.get("record_time"), "food_name": record["food_name"],
            "amount": record.get("amount"), "unit": record.get("unit"),
            "calories": record.get("calories"), "protein_g": record.get("protein_g"),
            "carbs_g": record.get("carbs_g"), "fat_g": record.get("fat_g"),
            "status": record.get("status", "confirmed"),
            "source_message_id": record.get("source_message_id"), "created_at": utc_now(),
        }
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO diet_records
                (id, user_id, record_date, record_time, food_name, amount, unit,
                 calories, protein_g, carbs_g, fat_g, status, source_message_id, created_at)
                VALUES (:id, :user_id, :record_date, :record_time, :food_name,
                 :amount, :unit, :calories, :protein_g, :carbs_g, :fat_g,
                 :status, :source_message_id, :created_at)""",
                item,
            )
        return item

    def add_exercise_record(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        self.ensure_user(user_id)
        item = {
            "id": new_id("exercise"), "user_id": user_id,
            "record_date": record.get("record_date", date.today().isoformat()),
            "record_time": record.get("record_time"), "exercise_name": record["exercise_name"],
            "duration_minutes": record.get("duration_minutes"),
            "distance_km": record.get("distance_km"), "intensity": record.get("intensity"),
            "met": record.get("met"), "calories_burned": record.get("calories_burned"),
            "status": record.get("status", "confirmed"),
            "source_message_id": record.get("source_message_id"), "created_at": utc_now(),
        }
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO exercise_records
                (id, user_id, record_date, record_time, exercise_name,
                 duration_minutes, distance_km, intensity, met, calories_burned,
                 status, source_message_id, created_at)
                VALUES (:id, :user_id, :record_date, :record_time, :exercise_name,
                 :duration_minutes, :distance_km, :intensity, :met,
                 :calories_burned, :status, :source_message_id, :created_at)""",
                item,
            )
        return item

    def add_body_record(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        self.ensure_user(user_id)
        item = {
            "id": new_id("body"), "user_id": user_id,
            "record_date": record.get("record_date", date.today().isoformat()),
            "weight_kg": record.get("weight_kg"), "waist_cm": record.get("waist_cm"),
            "steps": record.get("steps"), "sleep_hours": record.get("sleep_hours"),
            "fatigue_level": record.get("fatigue_level"), "note": record.get("note"),
            "source_message_id": record.get("source_message_id"), "created_at": utc_now(),
        }
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO body_life_records
                (id, user_id, record_date, weight_kg, waist_cm, steps, sleep_hours,
                 fatigue_level, note, source_message_id, created_at)
                VALUES (:id, :user_id, :record_date, :weight_kg, :waist_cm,
                 :steps, :sleep_hours, :fatigue_level, :note,
                 :source_message_id, :created_at)""",
                item,
            )
        return item

    def list_pending_records(self, user_id: str) -> list[dict[str, Any]]:
        diet = self.fetch_all(
            """SELECT id, 'diet' AS record_type, food_name AS name, amount, unit,
            NULL AS duration_minutes, NULL AS intensity, created_at
            FROM diet_records WHERE user_id = ? AND status = 'pending'
            ORDER BY created_at DESC LIMIT 5""",
            (user_id,),
        )
        exercise = self.fetch_all(
            """SELECT id, 'exercise' AS record_type, exercise_name AS name,
            NULL AS amount, NULL AS unit, duration_minutes, intensity, created_at
            FROM exercise_records WHERE user_id = ? AND status = 'pending'
            ORDER BY created_at DESC LIMIT 5""",
            (user_id,),
        )
        return sorted(diet + exercise, key=lambda item: item["created_at"], reverse=True)[:8]

    def resolve_diet_record(
        self,
        user_id: str,
        record_id: str,
        amount: float,
        unit: str,
        calories: float,
    ) -> dict[str, Any] | None:
        self.execute(
            """UPDATE diet_records SET amount = ?, unit = ?, calories = ?, status = 'confirmed'
            WHERE id = ? AND user_id = ? AND status = 'pending'""",
            (amount, unit, calories, record_id, user_id),
        )
        return self.fetch_one("SELECT * FROM diet_records WHERE id = ? AND user_id = ?", (record_id, user_id))

    def resolve_exercise_record(
        self,
        user_id: str,
        record_id: str,
        intensity: str,
        met: float,
        calories_burned: float,
    ) -> dict[str, Any] | None:
        self.execute(
            """UPDATE exercise_records SET intensity = ?, met = ?, calories_burned = ?, status = 'confirmed'
            WHERE id = ? AND user_id = ? AND status = 'pending'""",
            (intensity, met, calories_burned, record_id, user_id),
        )
        return self.fetch_one("SELECT * FROM exercise_records WHERE id = ? AND user_id = ?", (record_id, user_id))

    def daily_summary(self, user_id: str, record_date: str | None = None) -> dict[str, Any]:
        target_date = record_date or date.today().isoformat()
        diet = self.fetch_one(
            """SELECT COALESCE(SUM(calories), 0) AS intake,
            COALESCE(SUM(protein_g), 0) AS protein
            FROM diet_records WHERE user_id = ? AND record_date = ? AND status = 'confirmed'""",
            (user_id, target_date),
        ) or {"intake": 0, "protein": 0}
        exercise = self.fetch_one(
            """SELECT COALESCE(SUM(calories_burned), 0) AS burn
            FROM exercise_records WHERE user_id = ? AND record_date = ? AND status = 'confirmed'""",
            (user_id, target_date),
        ) or {"burn": 0}
        plan = self.get_active_plan(user_id)
        profile = self.get_profile(user_id)
        latest_body = self.fetch_one(
            """SELECT weight_kg FROM body_life_records
            WHERE user_id = ? AND weight_kg IS NOT NULL
            ORDER BY record_date DESC, created_at DESC LIMIT 1""",
            (user_id,),
        )
        progress = 0.0
        if profile and profile.get("target_weight_kg"):
            start_weight = float(profile["current_weight_kg"])
            current_weight = float(latest_body["weight_kg"]) if latest_body else start_weight
            target_weight = float(profile["target_weight_kg"])
            denominator = start_weight - target_weight
            if denominator > 0:
                progress = min(100.0, max(0.0, (start_weight - current_weight) / denominator * 100))
        completed_days = self.fetch_all(
            """SELECT record_date FROM exercise_records
            WHERE user_id = ? AND status = 'confirmed'
            GROUP BY record_date HAVING SUM(calories_burned) >= 500
            ORDER BY record_date DESC""",
            (user_id,),
        )
        streak = 0
        expected_date = date.fromisoformat(target_date)
        for completed in completed_days:
            if date.fromisoformat(completed["record_date"]) != expected_date:
                break
            streak += 1
            expected_date -= timedelta(days=1)
        burn = round(float(exercise["burn"] or 0), 2)
        intake = round(float(diet["intake"] or 0), 2)
        target_calories = plan["daily_calorie_target"] if plan else None
        return {
            "date": target_date,
            "intake": intake,
            "protein": round(float(diet["protein"] or 0), 2),
            "burn": burn,
            "target_calories": target_calories,
            "target_protein": plan["daily_protein_target"] if plan else None,
            "remaining_calories": round(float(target_calories) - intake + burn, 2) if target_calories else None,
            "today_progress": min(100, round(burn / 500 * 100)),
            "total_progress": round(progress, 1),
            "streak": streak,
            "cheat_day_left": 6 - (streak % 6) if streak % 6 else ("今天！" if streak else 6),
        }

    def reset_daily_records(self, user_id: str, record_date: str | None = None) -> None:
        target_date = record_date or date.today().isoformat()
        with self.connect() as connection:
            connection.execute("UPDATE diet_records SET status = 'voided' WHERE user_id = ? AND record_date = ?", (user_id, target_date))
            connection.execute("UPDATE exercise_records SET status = 'voided' WHERE user_id = ? AND record_date = ?", (user_id, target_date))

    def reset_user(self, user_id: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def save_memory(self, user_id: str, memory: dict[str, Any]) -> dict[str, Any]:
        self.ensure_user(user_id)
        now = utc_now()
        existing = self.fetch_one(
            """SELECT * FROM user_memories
            WHERE user_id = ? AND category = ? AND content = ? AND status IN ('active', 'pending_confirmation')
            ORDER BY updated_at DESC LIMIT 1""",
            (user_id, memory["category"], memory["content"]),
        )
        if existing:
            self.execute(
                """UPDATE user_memories SET duration_type = ?, status = 'active',
                expires_at = ?, confidence = ?, is_confirmed = ?, source_message_id = ?,
                last_confirmed_at = ?, updated_at = ? WHERE id = ?""",
                (
                    memory["duration_type"], memory.get("expires_at"),
                    memory.get("confidence", 1), int(memory.get("is_confirmed", True)),
                    memory.get("source_message_id"), now, now, existing["id"],
                ),
            )
            return self.fetch_one("SELECT * FROM user_memories WHERE id = ?", (existing["id"],)) or {}

        item = {
            "id": new_id("memory"), "user_id": user_id,
            "category": memory["category"], "content": memory["content"],
            "duration_type": memory["duration_type"], "status": memory.get("status", "active"),
            "valid_from": memory.get("valid_from", now), "expires_at": memory.get("expires_at"),
            "confidence": memory.get("confidence", 1),
            "is_confirmed": int(memory.get("is_confirmed", True)),
            "source_message_id": memory.get("source_message_id"),
            "last_confirmed_at": now if memory.get("is_confirmed", True) else None,
            "updated_at": now,
        }
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO user_memories
                (id, user_id, category, content, duration_type, status, valid_from,
                 expires_at, confidence, is_confirmed, source_message_id,
                 last_confirmed_at, updated_at)
                VALUES (:id, :user_id, :category, :content, :duration_type, :status,
                 :valid_from, :expires_at, :confidence, :is_confirmed,
                 :source_message_id, :last_confirmed_at, :updated_at)""",
                item,
            )
        return item

    def list_active_memories(self, user_id: str) -> list[dict[str, Any]]:
        now = utc_now()
        self.execute(
            """UPDATE user_memories SET status = 'pending_confirmation', updated_at = ?
            WHERE user_id = ? AND status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?""",
            (now, user_id, now),
        )
        return self.fetch_all(
            """SELECT * FROM user_memories WHERE user_id = ?
            AND status IN ('active', 'pending_confirmation') ORDER BY updated_at DESC""",
            (user_id,),
        )

    def update_memory_status(self, user_id: str, memory_id: str, status: str) -> None:
        self.execute(
            "UPDATE user_memories SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (status, utc_now(), memory_id, user_id),
        )

    def get_summary(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM conversation_summaries WHERE user_id = ? AND conversation_id = ?",
            (user_id, conversation_id),
        )

    def upsert_summary(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
        range_start: str | None,
        range_end: str | None,
        message_count: int,
    ) -> dict[str, Any]:
        existing = self.get_summary(user_id, conversation_id)
        item = {
            "id": existing["id"] if existing else new_id("summary"),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "content": content,
            "range_start": range_start,
            "range_end": range_end,
            "message_count": message_count,
            "updated_at": utc_now(),
        }
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO conversation_summaries
                (id, user_id, conversation_id, content, range_start, range_end,
                 message_count, updated_at)
                VALUES (:id, :user_id, :conversation_id, :content, :range_start,
                 :range_end, :message_count, :updated_at)
                ON CONFLICT(user_id, conversation_id) DO UPDATE SET
                 content = excluded.content, range_start = excluded.range_start,
                 range_end = excluded.range_end, message_count = excluded.message_count,
                 updated_at = excluded.updated_at""",
                item,
            )
        return self.get_summary(user_id, conversation_id) or {}

    def upsert_knowledge_document(
        self, name: str, category: str, source: str, version: str
    ) -> dict[str, Any]:
        existing = self.fetch_one(
            "SELECT * FROM knowledge_documents WHERE source = ? AND version = ?",
            (source, version),
        )
        item = {
            "id": existing["id"] if existing else new_id("document"),
            "name": name, "category": category, "source": source,
            "version": version, "updated_at": utc_now(), "enabled": 1,
        }
        with self.connect() as connection:
            connection.execute(
                "UPDATE knowledge_documents SET enabled = 0 WHERE source = ? AND version <> ?",
                (source, version),
            )
            connection.execute(
                """INSERT INTO knowledge_documents
                (id, name, category, source, version, updated_at, enabled)
                VALUES (:id, :name, :category, :source, :version, :updated_at, :enabled)
                ON CONFLICT(source, version) DO UPDATE SET name = excluded.name,
                 category = excluded.category, updated_at = excluded.updated_at,
                 enabled = 1""",
                item,
            )
        return self.fetch_one("SELECT * FROM knowledge_documents WHERE source = ? AND version = ?", (source, version)) or {}

    def replace_knowledge_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            old_ids = connection.execute(
                "SELECT id FROM knowledge_chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
            connection.executemany(
                "DELETE FROM knowledge_chunks_fts WHERE chunk_id = ?",
                [(row["id"],) for row in old_ids],
            )
            connection.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
            connection.executemany(
                """INSERT INTO knowledge_chunks
                (id, document_id, content, chunk_index, category, tags,
                 suitable_for, restrictions, enabled, updated_at)
                VALUES (:id, :document_id, :content, :chunk_index, :category,
                 :tags, :suitable_for, :restrictions, :enabled, :updated_at)""",
                chunks,
            )
            connection.executemany(
                "INSERT INTO knowledge_chunks_fts (chunk_id, category, terms) VALUES (?, ?, ?)",
                [
                    (
                        chunk["id"],
                        chunk["category"],
                        " ".join(_keyword_terms(chunk["content"])),
                    )
                    for chunk in chunks
                ],
            )

    def list_knowledge_chunks(self, category: str | None = None) -> list[dict[str, Any]]:
        sql = """SELECT c.*, d.name AS document_name, d.source AS document_source
        FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
        WHERE c.enabled = 1 AND d.enabled = 1"""
        parameters: tuple[Any, ...] = ()
        if category:
            sql += " AND c.category = ?"
            parameters = (category,)
        return self.fetch_all(sql, parameters)

    def get_knowledge_chunks(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        return self.fetch_all(
            f"""SELECT c.*, d.name AS document_name, d.source AS document_source
            FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.id IN ({placeholders}) AND c.enabled = 1 AND d.enabled = 1""",
            tuple(chunk_ids),
        )

    def search_knowledge_keywords(
        self,
        query: str,
        category: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        match_query = _fts_query(query)
        if not match_query:
            return []
        sql = """SELECT c.*, d.name AS document_name, d.source AS document_source,
        bm25(knowledge_chunks_fts) AS keyword_score
        FROM knowledge_chunks_fts
        JOIN knowledge_chunks c ON c.id = knowledge_chunks_fts.chunk_id
        JOIN knowledge_documents d ON d.id = c.document_id
        WHERE knowledge_chunks_fts MATCH ? AND c.enabled = 1 AND d.enabled = 1"""
        parameters: list[Any] = [match_query]
        if category:
            sql += " AND c.category = ?"
            parameters.append(category)
        sql += " ORDER BY keyword_score LIMIT ?"
        parameters.append(limit)
        return self.fetch_all(sql, tuple(parameters))

    def has_legacy_embeddings(self) -> bool:
        columns = self.fetch_all("PRAGMA table_info(knowledge_chunks)")
        names = {column["name"] for column in columns}
        return "embedding" in names or "embedding_model" in names

    def list_legacy_vector_chunks(self) -> list[dict[str, Any]]:
        if not self.has_legacy_embeddings():
            return []
        return self.fetch_all(
            """SELECT c.*, d.name AS document_name, d.source AS document_source,
            d.version AS document_version
            FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.enabled = 1 AND d.enabled = 1 AND c.embedding IS NOT NULL"""
        )

    def drop_legacy_embedding_columns(self) -> None:
        if not self.has_legacy_embeddings():
            return
        with self.connect() as connection:
            connection.execute("DROP TABLE IF EXISTS knowledge_chunks_fts")
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(knowledge_chunks)")
            }
            if "embedding" in columns:
                connection.execute("ALTER TABLE knowledge_chunks DROP COLUMN embedding")
            if "embedding_model" in columns:
                connection.execute("ALTER TABLE knowledge_chunks DROP COLUMN embedding_model")
            connection.execute(
                """CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(
                chunk_id UNINDEXED, category UNINDEXED, terms)"""
            )
            self._rebuild_knowledge_fts(connection)

    def vacuum(self) -> None:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("VACUUM")
        finally:
            connection.close()


database = Database()
