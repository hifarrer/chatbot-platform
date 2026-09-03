#!/usr/bin/env python3
"""
Migration: add Chatbot.model_alias and convert the global 'openai_model' setting
from a raw OpenAI model id to an Owlbee tier alias (sol / terra / luna).

Existing chatbots are deliberately left with model_alias = NULL, which means
"follow the global default" - exactly what every bot does today. So this
migration changes no behavior on its own.

Idempotent: safe to run repeatedly.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Chatbot, Settings
from migrate_phase2_common import ensure_phase2_columns
from services import model_catalog


def migrate_add_chatbot_model():
    """Add model_alias to Chatbot and normalize the global model setting."""
    app = create_app()

    with app.app_context():
        try:
            print("Starting migration: Add model_alias to Chatbot, normalize openai_model setting...")

            print("Ensuring Phase 2 columns exist...")
            ensure_phase2_columns(db)
            print("  Existing chatbots keep model_alias = NULL (follow the global default).")

            # Convert the global setting from a raw model id to a tier alias.
            setting = Settings.query.filter_by(key='openai_model').first()
            if not setting:
                print(f"No 'openai_model' setting found. Creating it as '{model_catalog.DEFAULT_ALIAS}'.")
                db.session.add(Settings(key='openai_model', value=model_catalog.DEFAULT_ALIAS))
            elif setting.value in model_catalog.CATALOG:
                print(f"Setting 'openai_model' is already a tier alias ('{setting.value}'). Skipping.")
            else:
                old_value = setting.value
                new_value = model_catalog.normalize_alias(old_value)
                profile = model_catalog.get_profile(new_value)
                setting.value = new_value
                print(f"Converting 'openai_model': {old_value!r} -> {new_value!r} "
                      f"({profile.display_name} = {profile.model_id})")
                if old_value not in model_catalog.LEGACY_MODEL_MAP:
                    print(f"  NOTE: {old_value!r} was not a known legacy id; "
                          f"defaulted to '{model_catalog.DEFAULT_ALIAS}'.")

            db.session.commit()

            total = Chatbot.query.count()
            explicit = Chatbot.query.filter(Chatbot.model_alias.isnot(None)).count()
            print(f"Chatbots: {total} total, {explicit} with an explicit tier, "
                  f"{total - explicit} following the global default.")
            print("Migration completed successfully!")

        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()
            raise


if __name__ == '__main__':
    migrate_add_chatbot_model()
