#!/usr/bin/env python3
"""
Shared helpers for the Phase 2 migrations (model tiers + token allowances).

Why this exists: the ORM maps every Phase 2 column, so any `Plan.query.all()`
emits a SELECT naming all of them. A script that added only its own columns and
then ran an ORM query would blow up on a database where a sibling script had not
run yet. So each script ensures the *whole* Phase 2 column set before touching
the ORM, which also makes the three scripts safe to run in any order.
"""

# (table, column, DDL type). Every one is nullable, so on Postgres each ALTER is
# a metadata-only change - no table rewrite, no long lock, safe on a live DB.
PHASE2_COLUMNS = [
    ('chatbot',      'model_alias',         'VARCHAR(20)'),
    ('plan',         'allowed_models',      'TEXT'),
    ('plan',         'web_search_enabled',  'BOOLEAN DEFAULT FALSE'),
    ('plan',         'monthly_token_limit', 'BIGINT'),
    ('conversation', 'prompt_tokens',       'INTEGER'),
    ('conversation', 'completion_tokens',   'INTEGER'),
    ('conversation', 'total_tokens',        'INTEGER'),
    ('conversation', 'model_alias',         'VARCHAR(20)'),
]


def ensure_phase2_columns(db, verbose=True):
    """Add any missing Phase 2 column. Idempotent; returns the list added."""
    from sqlalchemy import inspect, text

    added = []
    for table, column, ddl_type in PHASE2_COLUMNS:
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
