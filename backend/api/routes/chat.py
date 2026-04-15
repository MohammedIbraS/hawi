from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional

from backend.services.auth import get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])
_bearer = HTTPBearer(auto_error=False)


class ChatRequest(BaseModel):
    query: str
    entity_filter: Optional[str] = None
    doc_type_filter: Optional[str] = None
    chat_history: Optional[list[dict]] = None
    session_id: Optional[str] = None


class EvalResponse(BaseModel):
    answer: str
    contexts: list[str]          # raw chunk text, one entry per retrieved chunk
    sources: list[dict]


@router.post("/eval", response_model=EvalResponse)
async def chat_eval(request: Request, body: ChatRequest):
    """Non-streaming endpoint for RAGAS evaluation. Returns full answer + raw contexts."""
    rag = request.app.state.rag
    answer, contexts, sources = await rag.get_answer(
        query=body.query,
        entity_filter=body.entity_filter,
        doc_type_filter=body.doc_type_filter,
        chat_history=body.chat_history,
    )
    return EvalResponse(answer=answer, contexts=contexts, sources=sources)


@router.post("")
async def chat(request: Request, body: ChatRequest):
    rag = request.app.state.rag

    # Resolve optional user from Bearer token
    credentials: Optional[HTTPAuthorizationCredentials] = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        from fastapi.security import HTTPAuthorizationCredentials as Creds
        credentials = Creds(scheme="Bearer", credentials=auth_header[7:])
    user = get_current_user(credentials)

    return StreamingResponse(
        rag.stream_answer(
            query=body.query,
            entity_filter=body.entity_filter,
            doc_type_filter=body.doc_type_filter,
            chat_history=body.chat_history,
            session_id=body.session_id,
            user_id=str(user.id) if user else None,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
