"""add staff schedule entries

Revision ID: 7b2e4c9a1f63
Revises: 09abe20d256d
Create Date: 2026-10-01 17:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b2e4c9a1f63'
down_revision: Union[str, Sequence[str], None] = '09abe20d256d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'staff_schedule_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('school_id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('staff_id', sa.UUID(), nullable=True),
        sa.Column('teacher_name', sa.String(length=255), nullable=True),
        sa.Column('day_of_week', sa.String(length=20), nullable=False),
        sa.Column('period', sa.Integer(), nullable=False),
        sa.Column('period_label', sa.String(length=20), nullable=True),
        sa.Column('start_minute', sa.Integer(), nullable=False),
        sa.Column('end_minute', sa.Integer(), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('block_subject', sa.String(length=100), nullable=True),
        sa.Column('room', sa.String(length=100), nullable=True),
        sa.Column('grade', sa.String(length=50), nullable=True),
        sa.Column('service_type', sa.String(length=100), nullable=True),
        sa.Column('delivery', sa.String(length=20), nullable=True),
        sa.Column('is_pullout', sa.Boolean(), nullable=False),
        sa.Column('is_flex_period', sa.Boolean(), nullable=False),
        sa.Column('student_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['schedule_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['staff_id'], ['staff_members.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_staff_schedule_run_staff', 'staff_schedule_entries',
        ['run_id', 'staff_id'], unique=False,
    )
    op.create_index(
        'idx_staff_schedule_slot', 'staff_schedule_entries',
        ['run_id', 'staff_id', 'day_of_week', 'period'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_staff_schedule_slot', table_name='staff_schedule_entries')
    op.drop_index('idx_staff_schedule_run_staff', table_name='staff_schedule_entries')
    op.drop_table('staff_schedule_entries')
