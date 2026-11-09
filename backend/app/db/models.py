"""Every table model, imported in one place.

A foreign key names another table ("users.id"), and SQLAlchemy finds that table only once its
model has been imported; until then no row can be saved. app/db/session.py and alembic/env.py
import this module, so every table is always known. A new domain's models module gets a line here.
"""

import app.applications.models  # noqa: F401
import app.auth.models  # noqa: F401
import app.companies.models  # noqa: F401
import app.conversations.models  # noqa: F401
import app.friends.models  # noqa: F401
import app.game.models  # noqa: F401
import app.jobs.models  # noqa: F401
import app.media.models  # noqa: F401
import app.users.models  # noqa: F401
