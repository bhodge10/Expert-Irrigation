"""messages carry an AI-drafted reply awaiting a human

Revision ID: e9f3a1c85d27
Revises: c41d9a7e52b0
Create Date: 2026-08-16 11:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f3a1c85d27'
down_revision: Union[str, Sequence[str], None] = 'c41d9a7e52b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('draft_reply', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('draft_reply')
