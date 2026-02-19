"""
merge_all_branches

Revision ID: 03b221adf0f5
Revises: 003_computation_tables, 006_telegram_users
Create Date: 2026-02-16 12:55:46.255071
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '03b221adf0f5'
down_revision: Union[str, None] = ('003_computation_tables', '006_telegram_users')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
