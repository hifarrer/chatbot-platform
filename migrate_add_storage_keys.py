#!/usr/bin/env python3
"""
Migration: Document.storage_key (Phase 4, object storage).

Adds one nullable column and reports how many documents still need their files
copied into Bunny. It does NOT move any files - that is migrate_to_bunny.py,
which must run on the live instance before the cutover deploy.

Safe to run against the live database with no deploy: a nullable ALTER on
Postgres is metadata-only, and nothing reads the column until the cutover.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Document
from migrate_phase4_common import ensure_phase4_columns


def migrate_add_storage_keys():
    app = create_app()

    with app.app_context():
        try:
            print("Starting migration: document storage keys...")

            print("Ensuring Phase 2 + 3 + 4 columns exist...")
            ensure_phase4_columns(db)

            total = Document.query.count()
            pending = Document.query.filter(Document.storage_key.is_(None)).count()
            migrated = total - pending

            print(f"\n  documents total          : {total}")
            print(f"  already in object storage: {migrated}")
            print(f"  still on local disk       : {pending}")

            if pending:
                print("\nThose rows still point at a local file path. Run "
                      "migrate_to_bunny.py on the instance that still HAS those files, "
                      "before deploying the cutover - a deploy replaces the container "
                      "filesystem and the files are gone.")
            else:
                print("\nEvery document row has a storage key.")

            db.session.commit()
            print("Migration completed successfully!")

        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()
            raise


if __name__ == '__main__':
    migrate_add_storage_keys()
