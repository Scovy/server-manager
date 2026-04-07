"""add_apps_table

Revision ID: 8f3f6b4d02ac
Revises: d13bf77e3e28
Create Date: 2026-04-07 19:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f3f6b4d02ac"
down_revision: Union[str, None] = "d13bf77e3e28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "apps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column("app_name", sa.String(), nullable=False),
        sa.Column("container_name", sa.String(), nullable=False),
        sa.Column("host_port", sa.Integer(), nullable=False),
        sa.Column("app_dir", sa.String(), nullable=False),
        sa.Column("compose_path", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_name"),
        sa.UniqueConstraint("container_name"),
    )


def downgrade() -> None:
    op.drop_table("apps")
