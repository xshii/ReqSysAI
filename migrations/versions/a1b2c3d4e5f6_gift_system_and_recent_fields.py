"""Gift system + recent unmigrated fields

Revision ID: a1b2c3d4e5f6
Revises: 42c834766431
Create Date: 2026-03-29

New tables: gift_items, gift_records
New columns on incentives: gift_status, gift_item_id, gift_selected_at,
    gift_notified_at, gift_expires_at, gift_notify_count
New columns on gift_items: picks
New table: activity_timers (was created via db.create_all but no migration)
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '42c834766431'
branch_labels = None
depends_on = None


def upgrade():
    # gift_items table
    op.create_table('gift_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('link', sa.String(500), nullable=True),
        sa.Column('image', sa.String(300), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('picks', sa.Integer(), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # gift_records table (per-person gift selection tracking)
    op.create_table('gift_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('incentive_id', sa.Integer(), sa.ForeignKey('incentives.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('gift_item_id', sa.Integer(), sa.ForeignKey('gift_items.id'), nullable=True),
        sa.Column('status', sa.String(20), default='pending'),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('selected_at', sa.DateTime(), nullable=True),
        sa.Column('purchased_at', sa.DateTime(), nullable=True),
        sa.Column('notify_count', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # activity_timers table
    op.create_table('activity_timers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('activity', sa.String(30), nullable=False),
        sa.Column('label', sa.String(50), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # New columns on incentives
    with op.batch_alter_table('incentives') as batch_op:
        batch_op.add_column(sa.Column('gift_status', sa.String(20), nullable=True))
        batch_op.add_column(sa.Column('gift_item_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('gift_selected_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('gift_notified_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('gift_expires_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('gift_notify_count', sa.Integer(), server_default='0'))

    # category_l1/l2 are computed properties, no DB change needed
    # category field on requirements already added in previous migration


def downgrade():
    with op.batch_alter_table('incentives') as batch_op:
        batch_op.drop_column('gift_notify_count')
        batch_op.drop_column('gift_expires_at')
        batch_op.drop_column('gift_notified_at')
        batch_op.drop_column('gift_selected_at')
        batch_op.drop_column('gift_item_id')
        batch_op.drop_column('gift_status')

    op.drop_table('activity_timers')
    op.drop_table('gift_records')
    op.drop_table('gift_items')
