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

company_status = postgresql.ENUM("active", "deleted", name="company_status", create_type=False)
job_status = postgresql.ENUM("draft", "open", "deleted", name="job_status", create_type=False)
job_salary_type = postgresql.ENUM(
    "hourly", "daily", "weekly", "monthly", name="job_salary_type", create_type=False
)
job_schedule = postgresql.ENUM(
    "full_time", "part_time", "internship", name="job_schedule", create_type=False
)
job_urgency = postgresql.ENUM("normal", "urgent", "hot", name="job_urgency", create_type=False)
moderation_status = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    "moderation_error",
    name="moderation_status",
    create_type=False,
)
lifecycle_status = postgresql.ENUM(
    "loaded", "posted", "unposted", "deleted", name="lifecycle_status", create_type=False
)
video_rating = postgresql.ENUM("A", "B", "C", name="video_rating", create_type=False)

ENUMS = [
    user_status,
    friendship_status,
    company_status,
    job_status,
    job_salary_type,
    job_schedule,
    job_urgency,
    moderation_status,
    lifecycle_status,
    video_rating,
]


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
    # PostGIS adds map types and functions (jobs.location_point). The postgis image already
    # has it; this line is for a database that does not.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
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

    # Companies and jobs ------------------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        reference("owner_user_id", "users", "CASCADE"),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("logo_object_key", sa.String(500)),
        sa.Column("status", company_status, nullable=False, server_default="active"),
        sa.Column("country", sa.String(100)),
        sa.Column("city", sa.String(100)),
        sa.Column("district", sa.String(100)),
        sa.Column("country_code", sa.String(2)),
        reference("created_by_id", "users", "SET NULL", nullable=True),
        reference("updated_by_id", "users", "SET NULL", nullable=True),
        *timestamps(),
    )
    # One active company per owner; deleted companies do not count.
    op.create_index(
        "uq_companies_owner_active",
        "companies",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        reference("owner_id", "companies", "CASCADE"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="draft"),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("location", sa.String(150), nullable=False),
        sa.Column("salary_amount", sa.Numeric(12, 2)),
        sa.Column("salary_type", job_salary_type, nullable=False, server_default="monthly"),
        sa.Column("salary_currency", sa.String(3)),
        sa.Column("schedule", job_schedule, nullable=False, server_default="full_time"),
        sa.Column("urgency", job_urgency, nullable=False, server_default="normal"),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        reference("created_by_id", "users", "SET NULL", nullable=True),
        reference("updated_by_id", "users", "SET NULL", nullable=True),
        *timestamps(),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        sa.CheckConstraint("salary_amount >= 0", name="salary_not_negative"),
        sa.CheckConstraint("salary_currency ~ '^[A-Z]{3}$'", name="currency_iso_4217"),
    )
    # SQLAlchemy has no words for the next parts, so they are plain SQL.
    # The map point is computed by PostgreSQL from latitude and longitude.
    op.execute(
        "ALTER TABLE jobs ADD COLUMN location_point geography(Point, 4326) NOT NULL "
        "GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) "
        "STORED"
    )
    # Before every insert or update, PostgreSQL's own tsvector_update_trigger() fills
    # search_vector with the English words of title and description.
    op.execute(
        "CREATE TRIGGER jobs_search_vector_update BEFORE INSERT OR UPDATE ON jobs "
        "FOR EACH ROW EXECUTE FUNCTION "
        "tsvector_update_trigger(search_vector, 'pg_catalog.english', title, description)"
    )
    # GiST answers "jobs within 10 km" fast; GIN answers "jobs containing these words" fast.
    op.create_index("ix_jobs_location_point", "jobs", ["location_point"], postgresql_using="gist")
    op.create_index("ix_jobs_search_vector", "jobs", ["search_vector"], postgresql_using="gin")

    # Videos ------------------------------------------------------------------------------
    op.create_table(
        "intro_videos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        reference("user_id", "users", "CASCADE"),
        sa.Column("object_key", sa.String(500), nullable=False, unique=True),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("moderation_status", moderation_status, nullable=False, server_default="pending"),
        sa.Column("rejected_reason", sa.Text()),
        sa.Column("lifecycle_status", lifecycle_status, nullable=False, server_default="loaded"),
        sa.Column("video_rating", video_rating, nullable=False, server_default="B"),
        *timestamps(),
    )
    # Only one posted video per user.
    op.create_index(
        "uq_intro_videos_user_id_posted",
        "intro_videos",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle_status = 'posted'"),
    )


def downgrade() -> None:
    # Children before parents (a table's trigger and indexes go with it), then the enum types.
    # The postgis extension stays: it belongs to the database, not to this migration.
    op.drop_table("intro_videos")
    op.drop_table("jobs")
    op.drop_table("companies")
    op.drop_table("friendships")
    op.drop_table("password_reset_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("users")

    for enum in ENUMS:
        enum.drop(op.get_bind())
