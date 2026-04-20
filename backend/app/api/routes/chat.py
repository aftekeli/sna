from __future__ import annotations

import json
import queue
import threading
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.chat import ChatRuntimeService
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    method: str = Field(default="kg_rag", pattern="^kg_rag$")
    stream: bool = False


def get_chat_service(settings: Settings = Depends(get_settings)) -> ChatRuntimeService:
    return ChatRuntimeService(settings)


def _sse_event(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/bootstrap")
def get_chat_bootstrap(service: ChatRuntimeService = Depends(get_chat_service)) -> dict[str, Any]:
    return service.bootstrap()


@router.post("/sessions")
def create_chat_session(service: ChatRuntimeService = Depends(get_chat_service)) -> dict[str, Any]:
    return service.create_session()


@router.get("/sessions/{session_id}")
def get_chat_session(
    session_id: str,
    service: ChatRuntimeService = Depends(get_chat_service),
) -> dict[str, Any]:
    return service.get_session(session_id)


@router.post("/sessions/{session_id}/messages")
def run_chat_message(
    session_id: str,
    request: ChatMessageRequest,
    service: ChatRuntimeService = Depends(get_chat_service),
) -> dict[str, Any]:
    return service.run_turn(session_id=session_id, message=request.message, method=request.method)


@router.post("/sessions/{session_id}/messages/stream")
def stream_chat_message(
    session_id: str,
    request: ChatMessageRequest,
    service: ChatRuntimeService = Depends(get_chat_service),
) -> StreamingResponse:
    event_queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

    def emit_event(event_name: str, payload: dict[str, Any]) -> None:
        event_queue.put((event_name, payload))

    def worker() -> None:
        try:
            service.run_turn(
                session_id=session_id,
                message=request.message,
                method=request.method,
                emit_event=emit_event,
            )
        finally:
            event_queue.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def event_stream():
        yield _sse_event("ack", {"session_id": session_id, "method": request.method})
        while True:
            item = event_queue.get()
            if item is None:
                break
            event_name, payload = item
            yield _sse_event(event_name, payload)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
