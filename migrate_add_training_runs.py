#!/usr/bin/env python3
"""
Migration: training run tracking (Phase 3).

- Chatbot.last_trained_at, Chatbot.last_training_run_id
- the training_run table (created by db.create_all(), verified here)
- backfills last_trained_at from each artifact's mtime, and audits the
  "is_trained but no artifact on disk" case a deploy leaves behind

Idempotent: every column is guarded independently, so a partial run resumes.
"""

import os
import sys
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Chatbot
from migrate_phase3_common import ensure_phase3_columns


def migrate_add_training_runs():
    """Add training run schema and backfill last_trained_at."""
    app = create_app()

    with app.app_context():
        try:
            print("Starting migration: training run tracking...")

            from sqlalchemy import text
            from services.chatbot_trainer import get_trainer

            print("Ensuring Phase 2 + Phase 3 columns exist...")
            ensure_phase3_columns(db)

            # create_app() already ran db.create_all(), which creates training_run
            # if it was missing. Verify it explicitly rather than assuming.
            print("Verifying training_run table...")
            db.create_all()
            count = db.session.execute(text("SELECT COUNT(*) FROM training_run")).scalar()
            print(f"  training_run table present ({count} rows).")

            # Backfill last_trained_at from the artifact's mtime. Bots marked
            # trained with no artifact are the deploy-wipe casualties - name them
            # loudly, because until now the only way to discover one was for a
            # customer's visitor to get a useless answer.
            print("Backfilling chatbot.last_trained_at...")
            trainer = get_trainer()
            missing = []
            for chatbot in Chatbot.query.order_by(Chatbot.id).all():
                if not chatbot.is_trained:
                    continue
                if chatbot.last_trained_at is not None:
                    print(f"  chatbot {chatbot.id} ({chatbot.name!r}): already set. Leaving as is.")
                    continue
                key = trainer.artifact_key(chatbot.id)
                info = None
                try:
                    from services.object_storage import PRIVATE, get_storage
                    info = get_storage().stat(PRIVATE, key)
                except Exception as error:
                    print(f"  chatbot {chatbot.id}: could not stat {key}: {error}")
                if info:
                    chatbot.last_trained_at = datetime.utcnow()
                    print(f"  chatbot {chatbot.id} ({chatbot.name!r}): artifact present")
                else:
                    missing.append(chatbot)
                    print(f"  MISSING ARTIFACT: chatbot {chatbot.id} ({chatbot.name!r}) is "
                          f"marked trained but {key} does not exist. It will answer badly "
                          f"until its owner retrains.")

            db.session.commit()

            if missing:
                print(f"\n{len(missing)} chatbot(s) are marked trained with no artifact on disk:")
                for chatbot in missing:
                    print(f"  - {chatbot.id}: {chatbot.name!r} (owner user_id={chatbot.user_id})")
                print("This is the deploy-wipe problem; see TRAINING_DATA_DIR in render.yaml.")

            print("Migration completed successfully!")

        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()
            raise


if __name__ == '__main__':
    migrate_add_training_runs()
