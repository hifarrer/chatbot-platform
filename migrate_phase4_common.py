#!/usr/bin/env python3
"""
Shared helper for the Phase 4 migration (object storage).

Same reasoning as the Phase 2 and Phase 3 helpers: the ORM maps every column of
every phase, so any `Document.query` emits a SELECT naming them all. Phase 4
therefore chains Phase 3, which chains Phase 2 - making this safe to run against
a database at any point in the sequence.
"""

# (table, column, DDL type). Nullable, so on Postgres the ALTER is metadata-only
# - no table rewrite, no long lock, safe on a live database with no deploy.
PHASE4_COLUMNS = [
    ('document', 'storage_key', 'VARCHAR(500)'),
]


def ensure_phase4_columns(db, verbose=True):
    """Add any missing Phase 2, 3 or 4 column. Idempotent; returns what it added."""
    from sqlalchemy import inspect, text
    from migrate_phase3_common import ensure_phase3_columns

    added = list(ensure_phase3_columns(db, verbose=verbose))

    for table, column, ddl_type in PHASE4_COLUMNS:
        inspector = inspect(db.engine)  # re-inspect: the cache is per instance
        columns = [col['name'] for col in inspector.get_columns(table)]
        if column in columns:
            if verbose:
                print(f"  {table}.{column}: already exists")
            continue
        if verbose:
            print(f"  {table}.{column}: adding ({ddl_type})")
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        db.session.commit()
        added.append(f"{table}.{column}")
    return added
