"""password change requests needing admin approval

Revision ID: a3c8e5d71b42
Revises: 7b2e4c9a1f63
Create Date: 2026-10-09 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c8e5d71b42'
down_revision: Union[str, Sequence[str], None] = '7b2e4c9a1f63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('password_changed_at', sa.DateTime(), nullable=True))

    op.create_table(
        'password_change_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('school_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('new_password_hash', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_password_change_requests_school_status',
        'password_change_requests', ['school_id', 'status'],
    )
    op.create_index(
        'ix_password_change_requests_user',
        'password_change_requests', ['user_id'],
    )
    # At most one pending request per user, enforced by the database.
    op.create_index(
        'uq_password_change_requests_one_pending',
        'password_change_requests', ['user_id'],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_password_change_requests_one_pending', table_name='password_change_requests')
    op.drop_index('ix_password_change_requests_user', table_name='password_change_requests')
    op.drop_index('ix_password_change_requests_school_status', table_name='password_change_requests')
    op.drop_table('password_change_requests')
    op.drop_column('users', 'password_changed_at')
