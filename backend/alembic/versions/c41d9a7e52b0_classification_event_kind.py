"""classification events carry a kind: model, correction, confirmation, rejection

Revision ID: c41d9a7e52b0
Revises: 0b7c649348bd
Create Date: 2026-08-16 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c41d9a7e52b0'
down_revision: Union[str, Sequence[str], None] = '0b7c649348bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default kept, matching the model default — a row inserted by code
    # that predates this column is by definition the model's own sort.
    with op.batch_alter_table('classification_events', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('kind', sa.String(length=16), nullable=False, server_default='model')
        )
        batch_op.create_index(batch_op.f('ix_classification_events_kind'), ['kind'], unique=False)

    # Existing rows: a user id on the row meant a human moved the message —
    # that is what this table recorded before kinds existed.
    op.execute(
        "UPDATE classification_events SET kind = 'correction' WHERE changed_by IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('classification_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_classification_events_kind'))
        batch_op.drop_column('kind')
