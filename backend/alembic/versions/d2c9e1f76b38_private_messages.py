"""messages carry a privacy flag and the list of who may see them

Revision ID: d2c9e1f76b38
Revises: b7f4a9d3c621
Create Date: 2026-08-19 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2c9e1f76b38'
down_revision: Union[str, Sequence[str], None] = 'b7f4a9d3c621'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_private', sa.Boolean(), nullable=False, server_default='0'
            )
        )
        batch_op.add_column(sa.Column('visible_to', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('visible_to')
        batch_op.drop_column('is_private')
