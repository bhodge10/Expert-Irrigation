"""private_senders — addresses and domains whose mail never enters the portal

Revision ID: b7f4a9d3c621
Revises: f2b8d6a41c93
Create Date: 2026-08-19 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f4a9d3c621'
down_revision: Union[str, Sequence[str], None] = 'f2b8d6a41c93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'private_senders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pattern', sa.String(length=255), nullable=False),
        sa.Column('added_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['added_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_private_senders_pattern'), 'private_senders', ['pattern'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_private_senders_pattern'), table_name='private_senders')
    op.drop_table('private_senders')
