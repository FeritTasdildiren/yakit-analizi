"""create predictions v5

Revision ID: 007
Revises: 03b221adf0f5
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '03b221adf0f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- predictions_v5 Table ---
    op.create_table(
        'predictions_v5',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('fuel_type', postgresql.ENUM('benzin', 'motorin', 'lpg', name='fuel_type_enum', create_type=False), nullable=False),
        sa.Column('stage1_probability', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('stage1_label', sa.Boolean(), nullable=True),
        sa.Column('first_event_direction', sa.SmallInteger(), nullable=True),
        sa.Column('first_event_amount', sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column('first_event_type', sa.String(length=12), nullable=True),
        sa.Column('net_amount_3d', sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column('model_version', sa.String(length=20), nullable=True),
        sa.Column('calibration_method', sa.String(length=20), nullable=True),
        sa.Column('alarm_triggered', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('alarm_suppressed', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('suppression_reason', sa.String(length=50), nullable=True),
        sa.Column('alarm_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_date', 'fuel_type', name='uq_predictions_v5_run_fuel')
    )

    # --- feature_snapshots_v5 Table ---
    op.create_table(
        'feature_snapshots_v5',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('fuel_type', postgresql.ENUM('benzin', 'motorin', 'lpg', name='fuel_type_enum', create_type=False), nullable=False),
        sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('feature_version', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_date', 'fuel_type', name='uq_feature_snapshots_v5_run_fuel')
    )


def downgrade() -> None:
    op.drop_table('feature_snapshots_v5')
    op.drop_table('predictions_v5')
