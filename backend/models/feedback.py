from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import uuid

from pipeline.catalog.models import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Nullable FK — guest users have no session; logged-in users do
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True)
    # Store enough context to reconstruct the exchange for golden dataset review
    query = Column(Text, nullable=False)
    answer_excerpt = Column(Text)          # first 500 chars of the assistant answer
    rating = Column(String(4), nullable=False)  # 'up' | 'down'
    comment = Column(Text)                 # optional free-text comment
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
