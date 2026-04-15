from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

from backend.services.auth import require_user
from backend.models.user import User
from backend.database import get_session

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionSummary(BaseModel):
    id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    message_count: int


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    sources: Optional[list] = None
    created_at: datetime


class SessionDetail(BaseModel):
    id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


@router.post("", response_model=SessionSummary, status_code=201)
def create_session(user: User = Depends(require_user)):
    from backend.models.chat import ChatSession

    with get_session() as db:
        s = ChatSession(user_id=user.id)
        db.add(s)
        db.flush()
        return SessionSummary(
            id=str(s.id),
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=0,
        )


@router.get("", response_model=list[SessionSummary])
def list_sessions(user: User = Depends(require_user)):
    from backend.models.chat import ChatSession, ChatMessage
    from sqlalchemy import func

    with get_session() as session:
        results = (
            session.query(
                ChatSession,
                func.count(ChatMessage.id).label("message_count"),
            )
            .outerjoin(ChatMessage)
            .filter(ChatSession.user_id == user.id)
            .group_by(ChatSession.id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        )
        return [
            SessionSummary(
                id=str(s.id),
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=count,
            )
            for s, count in results
        ]


@router.get("/{session_id}", response_model=SessionDetail)
def get_session_detail(session_id: UUID, user: User = Depends(require_user)):
    from backend.models.chat import ChatSession, ChatMessage

    with get_session() as db:
        s = db.query(ChatSession).filter_by(id=session_id, user_id=user.id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = db.query(ChatMessage).filter_by(session_id=s.id).order_by(ChatMessage.created_at).all()
        return SessionDetail(
            id=str(s.id),
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            messages=[
                MessageOut(
                    id=str(m.id),
                    role=m.role,
                    content=m.content,
                    sources=m.sources,
                    created_at=m.created_at,
                )
                for m in messages
            ],
        )


@router.patch("/{session_id}", response_model=SessionSummary)
def rename_session(session_id: UUID, body: dict, user: User = Depends(require_user)):
    from backend.models.chat import ChatSession, ChatMessage
    from sqlalchemy import func

    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")

    with get_session() as db:
        s = db.query(ChatSession).filter_by(id=session_id, user_id=user.id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        s.title = title[:120]
        db.flush()
        count = db.query(func.count(ChatMessage.id)).filter_by(session_id=s.id).scalar() or 0
        return SessionSummary(
            id=str(s.id),
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=count,
        )


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: UUID, user: User = Depends(require_user)):
    from backend.models.chat import ChatSession

    with get_session() as db:
        s = db.query(ChatSession).filter_by(id=session_id, user_id=user.id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        db.delete(s)
