#!/usr/bin/env python3
"""
Shared helpers for the Phase 3 migration (training reliability).

Same reasoning as migrate_phase2_common.py: the ORM maps every column of both
phases, so any `Chatbot.query` emits a SELECT naming Phase 2 *and* Phase 3
columns. Phase 3 therefore chains Phase 2 rather than assuming it ran - which
also makes this script safe on a database at any point in the sequence.
"""

# (table, column, DDL type). Both are nullable, so on Postgres each ALTER is a
# metadata-only change - no table rewrite, no long lock, safe on a live DB.
# The training_run table itself is created by db.create_all(), not here.
PHASE3_COLUMNS = [
    ('chatbot', 'last_trained_at',      'TIMESTAMP'),
    ('chatbot', 'last_training_run_id', 'VARCHAR(36)'),
]


def ensure_phase3_columns(db, verbose=True):
    """Add any missing Phase 2 or Phase 3 column. Idempotent; returns what it added."""
    from sqlalchemy import inspect, text
    from migrate_phase2_common import ensure_phase2_columns

    added = list(ensure_phase2_columns(db, verbose=verbose))

    for table, column, ddl_type in PHASE3_COLUMNS:
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
