"""Initial schema: the tables of the new backend.

Revision ID: ed150e2c4d01
Revises:
Create Date: 2026-11-07 12:01:30.283120

Written by hand, one block per area. The models in app/<domain>/models.py describe the
same tables, and `alembic check` (run by tests/test_schema.py) proves the two agree.
Constraint and index names come from the naming convention in app/db/base.py,
for example uq_users_email or ix_refresh_tokens_user_id.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ed150e2c4d01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types: created before the tables that use them, dropped after them.
# create_type=False stops create_table from trying to create them a second time.
user_status = postgresql.ENUM("active", "deleted", name="user_status", create_type=False)
friendship_status = postgresql.ENUM(
    "pending", "accepted", "declined", name="friendship_status", create_type=False
)

ENUMS = [user_status, friendship_status]


def timestamps() -> list[sa.Column]:
    """created_at and updated_at, the same columns TimestampMixin adds to every model."""
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def reference(
    name: str, table: str, ondelete: str, nullable: bool = False, index: bool = True
) -> sa.Column:
    """A column holding the id of a row in another table (a foreign key), with an index.

    ondelete says what happens to this row when that row is deleted: CASCADE deletes it
    too, SET NULL empties the column. index=False when an index already starts with it.
    """
    return sa.Column(
        name,
        sa.BigInteger(),
        sa.ForeignKey(f"{table}.id", ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


def upgrade() -> None:
    for enum in ENUMS:
        enum.create(op.get_bind())

    # Accounts --------------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_name", sa.String(50)),
        sa.Column("last_name", sa.String(50)),
        sa.Column("position", sa.String(100)),
        sa.Column("birth_date", sa.Date()),
        sa.Column("bio", sa.String(500)),
        sa.Column("avatar_object_key", sa.String(500)),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", user_status, nullable=False, server_default="active"),
        *timestamps(),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        reference("user_id", "users", "CASCADE"),
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        *timestamps(),
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        reference("user_id", "users", "CASCADE"),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )

    # Friends ---------------------------------------------------------------------------
    op.create_table(
        "friendships",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        reference("requester_id", "users", "CASCADE"),
        reference("addressee_id", "users", "CASCADE"),
        sa.Column("status", friendship_status, nullable=False, server_default="pending"),
        *timestamps(),
        sa.CheckConstraint("requester_id <> addressee_id", name="not_self"),
    )
    # One live row per pair of users, whoever asked first; declined rows do not count.
    op.create_index(
        "uq_friendships_pair",
        "friendships",
        [
            sa.text("least(requester_id, addressee_id)"),
            sa.text("greatest(requester_id, addressee_id)"),
        ],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'accepted')"),
    )


def downgrade() -> None:
    # Children before parents, then the enum types.
    op.drop_table("friendships")
    op.drop_table("password_reset_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("users")

    for enum in ENUMS:
        enum.drop(op.get_bind())
