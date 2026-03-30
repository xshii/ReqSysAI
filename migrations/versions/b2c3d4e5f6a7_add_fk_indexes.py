"""add indexes on frequently-queried foreign key columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-29

Indexes on: todos.user_id, requirements.project_id, requirements.assignee_id,
requirements.parent_id, risks.owner_id, risks.tracker_id, risks.project_id,
pomodoro_sessions.todo_id
"""
from alembic import op

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_todos_user_id', 'todos', ['user_id'])
    op.create_index('ix_requirements_project_id', 'requirements', ['project_id'])
    op.create_index('ix_requirements_assignee_id', 'requirements', ['assignee_id'])
    op.create_index('ix_requirements_parent_id', 'requirements', ['parent_id'])
    op.create_index('ix_risks_owner_id', 'risks', ['owner_id'])
    op.create_index('ix_risks_tracker_id', 'risks', ['tracker_id'])
    op.create_index('ix_risks_project_id', 'risks', ['project_id'])
    op.create_index('ix_pomodoro_sessions_todo_id', 'pomodoro_sessions', ['todo_id'])


def downgrade():
    op.drop_index('ix_pomodoro_sessions_todo_id', 'pomodoro_sessions')
    op.drop_index('ix_risks_project_id', 'risks')
    op.drop_index('ix_risks_tracker_id', 'risks')
    op.drop_index('ix_risks_owner_id', 'risks')
    op.drop_index('ix_requirements_parent_id', 'requirements')
    op.drop_index('ix_requirements_assignee_id', 'requirements')
    op.drop_index('ix_requirements_project_id', 'requirements')
    op.drop_index('ix_todos_user_id', 'todos')
