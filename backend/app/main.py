from typing import Any, Dict

from fastapi import FastAPI
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent.graph import (
    chat_model,
    context_manager,
    fact_extractor,
    invoke_agent,
    knowledge_base,
)
from app.database import database
from app.domain import build_weight_loss_plan
from app.schemas import (
    ChatRequest,
    DietRecordInput,
    ExerciseRecordInput,
    MemoryStatusInput,
    ProfileInput,
    UserActionRequest,
)


app = FastAPI(
    title="AI 减脂教练 API",
    description="提供给 Next.js 前端调用的聊天接口",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest) -> JSONResponse:
    user_message = database.add_message(
        request.user_id, request.conversation_id, "user", request.message
    )
    try:
        result = invoke_agent(
            request.user_id,
            request.conversation_id,
            request.message,
            user_message["id"],
        )
        ai_response = result["reply"]
        database.add_message(
            request.user_id, request.conversation_id, "assistant", ai_response
        )
        context_manager.maybe_update_summary(request.user_id, request.conversation_id)
        return JSONResponse(
            content={
                "reply": ai_response,
                "message_id": user_message["id"],
                "dashboard": database.daily_summary(request.user_id),
                "sources": result.get("knowledge_sources", []),
                "actions": result.get("action_plan", []),
                "warnings": result.get("errors", []),
            }
        )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "reply": "本轮处理失败，消息已经保存，请稍后重试。",
                "error": str(exc),
            },
        )


@app.get("/")
def read_root() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    sqlite_ok = database.fetch_one("SELECT 1 AS ok") == {"ok": 1}
    knowledge = knowledge_base.health()
    return {
        "status": "ok" if sqlite_ok and knowledge["available"] else "degraded",
        "sqlite": {"available": sqlite_ok, "path": str(database.path)},
        "chroma": knowledge,
        "chat_model_available": chat_model is not None,
        "fact_model_available": fact_extractor.model is not None,
    }


@app.get("/api/bootstrap")
def bootstrap(
    user_id: str = Query(default="default"),
    conversation_id: str = Query(default="main"),
) -> Dict[str, Any]:
    database.ensure_user(user_id)
    profile = database.get_profile(user_id)
    return {
        "needs_onboarding": profile is None,
        "profile": profile,
        "plan": database.get_active_plan(user_id),
        "dashboard": database.daily_summary(user_id),
        "messages": database.list_messages(user_id, conversation_id, limit=50),
    }


@app.post("/api/profile")
def save_profile(request: ProfileInput) -> Dict[str, Any]:
    data = request.model_dump(exclude={"target_loss_speed", "user_id"})
    profile = database.upsert_profile(request.user_id, data)
    plan = database.create_plan(
        request.user_id,
        build_weight_loss_plan(profile, request.target_loss_speed),
    )
    return {"profile": profile, "plan": plan, "dashboard": database.daily_summary(request.user_id)}


@app.get("/api/dashboard")
def dashboard(user_id: str = Query(default="default")) -> Dict[str, Any]:
    return database.daily_summary(user_id)


@app.post("/api/records/diet")
def add_diet_record(request: DietRecordInput) -> Dict[str, Any]:
    record = database.add_diet_record(
        request.user_id, request.model_dump(exclude={"user_id"})
    )
    return {"record": record, "dashboard": database.daily_summary(request.user_id)}


@app.post("/api/records/exercise")
def add_exercise_record(request: ExerciseRecordInput) -> Dict[str, Any]:
    record = database.add_exercise_record(
        request.user_id, request.model_dump(exclude={"user_id"})
    )
    return {"record": record, "dashboard": database.daily_summary(request.user_id)}


@app.post("/api/reset/daily")
def reset_daily(request: UserActionRequest) -> Dict[str, Any]:
    database.reset_daily_records(request.user_id)
    return {"dashboard": database.daily_summary(request.user_id)}


@app.post("/api/reset/all")
def reset_all(request: UserActionRequest) -> Dict[str, bool]:
    database.reset_user(request.user_id)
    database.ensure_user(request.user_id)
    return {"ok": True}


@app.get("/api/memories")
def list_memories(user_id: str = Query(default="default")) -> Dict[str, Any]:
    return {"items": database.list_active_memories(user_id)}


@app.patch("/api/memories/{memory_id}")
def update_memory(memory_id: str, request: MemoryStatusInput) -> Dict[str, bool]:
    database.update_memory_status(request.user_id, memory_id, request.status)
    return {"ok": True}
