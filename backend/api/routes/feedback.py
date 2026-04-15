from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    query: str
    answer_excerpt: Optional[str] = None   # first ~500 chars of assistant answer
    rating: Literal["up", "down"]
    comment: Optional[str] = None
    session_id: Optional[str] = None


@router.post("", status_code=201)
async def submit_feedback(body: FeedbackRequest):
    """Record a thumbs-up or thumbs-down on an assistant answer."""
    from backend.database import get_session
    from backend.models.feedback import Feedback
    import uuid

    session_uuid = None
    if body.session_id:
        try:
            session_uuid = uuid.UUID(body.session_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid session_id format")

    def _save():
        with get_session() as db:
            db.add(Feedback(
                session_id=session_uuid,
                query=body.query[:1000],
                answer_excerpt=(body.answer_excerpt or "")[:500],
                rating=body.rating,
                comment=(body.comment or "")[:2000] or None,
            ))

    import asyncio
    await asyncio.to_thread(_save)
    return {"status": "ok"}
