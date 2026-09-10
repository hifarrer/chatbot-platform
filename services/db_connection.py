"""
PostgreSQL connection helper for the standalone maintenance scripts.

The application configures SQLAlchemy from DATABASE_URL (see create_app in
app.py). The scripts in the project root used to read a second, parallel set of
credentials instead - PGHOST, PGDATABASE, PGUSER, PGPASSWORD, PGPORT - which
described the same database twice and let the two copies drift apart: pointing
the app at a new database moved the app but left every script talking to the old
one. Everything now goes through DATABASE_URL and nothing reads the PG* vars.

Behaviour is fail-loud on purpose. These are operator tools run by hand, often
against production, so a missing or SQLite-shaped URL raises with the fix in the
message rather than surfacing later as a confusing libpq error.
"""
import os

from dotenv import load_dotenv

DATABASE_ENV_VAR = 'DATABASE_URL'


def get_database_url():
    """Return DATABASE_URL, normalised the same way app.py normalises it.

    Strips surrounding whitespace and quotes (a value exported by hand from a
    .env line often keeps its quotes) and rewrites the legacy postgres:// scheme
    that some hosts still hand out, which SQLAlchemy 1.4+ rejects.
    """
    load_dotenv()

    url = (os.environ.get(DATABASE_ENV_VAR) or '').strip().strip('"').strip("'")
    if not url:
        raise RuntimeError(
            '%s is not set. Add it to .env or export it, for example:\n'
            '  %s="postgresql://user:password@host:5432/dbname"'
            % (DATABASE_ENV_VAR, DATABASE_ENV_VAR)
        )

    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)

    return url


def get_postgres_connection(**kwargs):
    """Open a psycopg2 connection to the DATABASE_URL database.

    Extra keyword arguments are passed through to psycopg2.connect, so a caller
    can still ask for a cursor_factory or a connect_timeout.
    """
    import psycopg2

    url = get_database_url()
    if url.startswith('sqlite'):
        raise RuntimeError(
            '%s points at SQLite (%s), but this script requires PostgreSQL. '
            'Set %s to a postgresql:// URL.'
            % (DATABASE_ENV_VAR, url, DATABASE_ENV_VAR)
        )

    return psycopg2.connect(url, **kwargs)


def describe_target():
    """Host and database name only, never the credentials.

    Printed by the scripts on startup so it is obvious which database is about
    to be read or written - several of these tools delete rows.
    """
    import re

    url = get_database_url()
    return re.sub(r'://[^@]*@', '://', url)
