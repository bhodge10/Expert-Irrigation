"""the Other queue becomes Undetermined; Ignored arrives alongside it

Revision ID: f2b8d6a41c93
Revises: e9f3a1c85d27
Create Date: 2026-08-16 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b8d6a41c93'
down_revision: Union[str, Sequence[str], None] = 'e9f3a1c85d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Pure data remap — the queue column is a free string. Existing 'other'
    # rows become 'undetermined'; a follow-up `manage.py classify --all` run
    # re-sorts them under the four-queue rules (ignored vs undetermined).
    op.execute("UPDATE messages SET queue = 'undetermined' WHERE queue = 'other'")
    op.execute(
        "UPDATE classification_events SET from_queue = 'undetermined' "
        "WHERE from_queue = 'other'"
    )
    op.execute(
        "UPDATE classification_events SET to_queue = 'undetermined' "
        "WHERE to_queue = 'other'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE messages SET queue = 'other' WHERE queue IN ('undetermined', 'ignored')")
    op.execute(
        "UPDATE classification_events SET from_queue = 'other' "
        "WHERE from_queue IN ('undetermined', 'ignored')"
    )
    op.execute(
        "UPDATE classification_events SET to_queue = 'other' "
        "WHERE to_queue IN ('undetermined', 'ignored')"
    )
