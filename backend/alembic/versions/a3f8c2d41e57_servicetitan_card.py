"""messages carry a ServiceTitan card, display-only, a day at most

Revision ID: a3f8c2d41e57
Revises: d2c9e1f76b38
Create Date: 2026-10-05 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8c2d41e57'
down_revision: Union[str, Sequence[str], None] = 'd2c9e1f76b38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('servicetitan_card', sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column('servicetitan_checked_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('servicetitan_checked_at')
        batch_op.drop_column('servicetitan_card')
