"""add_feedback_table

Revision ID: 4f2e8a1c9d3b
Revises: 18cc00b55ea2
Create Date: 2026-03-17 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '4f2e8a1c9d3b'
down_revision: Union[str, None] = '18cc00b55ea2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('chat_sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('answer_excerpt', sa.Text(), nullable=True),
        sa.Column('rating', sa.String(4), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_feedback_session_id', 'feedback', ['session_id'])
    op.create_index('ix_feedback_rating', 'feedback', ['rating'])


def downgrade() -> None:
    op.drop_index('ix_feedback_rating', table_name='feedback')
    op.drop_index('ix_feedback_session_id', table_name='feedback')
    op.drop_table('feedback')
