"""Draws the database schema as an SVG, from the tables of a real database.

scripts/gen-schema-diagram.sh runs this inside its drawing image (eralchemy and Graphviz)
after the Alembic migrations built the throwaway database; it reads DATABASE_URL and prints
the SVG. Do not run it against the stack's database: run the shell script.

eralchemy reads every table back from the database and writes it as a box: its columns in
order, each with its type, NOT NULL when it is required, and the primary key underlined.
Each foreign key becomes a dashed line from the referenced id to the column that holds it,
labelled with how many rows each end can have: 1 (exactly one), {0,1} (none or one, when
the column may be empty) or 0..N (any number). Graphviz then places and draws the boxes.
"""

import os
import sys
from itertools import pairwise

import geoalchemy2  # noqa: F401  (lets SQLAlchemy read PostGIS's geography type)
import graphviz
from eralchemy.main import filter_resources, intermediary_to_dot
from eralchemy.models import Table
from eralchemy.sqla import column_to_intermediary, relation_to_intermediary
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.dialects import postgresql

# Not part of our data model: Alembic's record of the migrations that ran, and PostGIS's
# table of map projections.
LEFT_OUT = {"alembic_version", "spatial_ref_sys"}
# Tables per row. Three keeps the picture narrow enough to read at the README's width.
PER_ROW = 3


def postgres_type(column_type) -> str:
    """The type as PostgreSQL names it: an enum shows its own name (user_status), not a
    VARCHAR. TIMESTAMPTZ is PostgreSQL's own short name for TIMESTAMP WITH TIME ZONE."""
    name = column_type.compile(dialect=postgresql.dialect())
    return name.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ")


engine = create_engine(os.environ["DATABASE_URL"])
metadata = MetaData()
metadata.reflect(engine)
# The tables in the order the migrations created them (PostgreSQL numbers each new table
# one higher), so related tables sit next to each other, as in the migration.
with engine.connect() as connection:
    created = connection.execute(
        text(
            "SELECT relname FROM pg_class "
            "WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace ORDER BY oid"
        )
    ).scalars()
    names = [name for name in created if name in metadata.tables and name not in LEFT_OUT]
if not names:
    sys.exit("no table found: did the migrations run?")
db_tables = [metadata.tables[name] for name in names]

tables = [
    Table(
        name=table.name,
        columns=[column_to_intermediary(c, type_formatter=postgres_type) for c in table.columns],
    )
    for table in db_tables
]
relations = [
    relation_to_intermediary(foreign_key)
    for table in db_tables
    for foreign_key in sorted(table.foreign_keys, key=lambda fk: fk.parent.name)
]
# "original": the columns in the table's own order, the primary key first.
tables, relations = filter_resources(tables, relations, sort_mode="original")
source = intermediary_to_dot(tables, relations).decode()

# Layout: eralchemy puts the tables side by side (rankdir=LR), too wide for the README.
# Here they go top to bottom in rows of PER_ROW, in the order above (invisible edges keep
# that order); the foreign key lines no longer decide where a table goes (constraint=false),
# and lines that run side by side are merged (concentrate=true) so they take less room.
rows = [names[i : i + PER_ROW] for i in range(0, len(names), PER_ROW)]
layout = ["{rank=same; " + " ".join(f'"{name}";' for name in row) + "}" for row in rows]
invisible = "[style=invis, constraint=true]"
layout += [f'"{up[0]}" -- "{down[0]}" {invisible};' for up, down in pairwise(rows)]
layout += [f'"{left}" -- "{right}" {invisible};' for row in rows for left, right in pairwise(row)]
source = source.replace("rankdir=LR", "rankdir=TB, newrank=true, concentrate=true")
source = source.replace("minlen=2", "constraint=false")
source = source.rstrip().removesuffix("}") + "\n".join(layout) + "\n}\n"

sys.stdout.buffer.write(graphviz.Source(source, engine="dot").pipe(format="svg"))
