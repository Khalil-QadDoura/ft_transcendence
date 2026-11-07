"""The table base class: constraint names and the timestamp columns, checked on the SQL."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.db.mixins import TimestampMixin


def test_base_names_constraints_and_mixin_adds_timestamps():
    class Sample(TimestampMixin, Base):
        __tablename__ = "sample"
        id: Mapped[int] = mapped_column(primary_key=True)
        code: Mapped[str] = mapped_column(unique=True)

    try:
        sql = str(CreateTable(Sample.__table__).compile(dialect=postgresql.dialect()))
    finally:
        Base.metadata.remove(Sample.__table__)  # keep the test table out of migrations

    assert "CONSTRAINT pk_sample PRIMARY KEY (id)" in sql
    assert "CONSTRAINT uq_sample_code UNIQUE (code)" in sql
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
    assert "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
