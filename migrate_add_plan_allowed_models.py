#!/usr/bin/env python3
"""
Migration: add Plan.allowed_models and Plan.web_search_enabled.

allowed_models is a JSON array of tier aliases, mirroring how Plan.features
already stores a JSON list in a Text column.

Idempotent: safe to run repeatedly.
"""

import sys
import os
import json

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Plan
from migrate_phase2_common import ensure_phase2_columns
from services import model_catalog

# Backfill by plan name. Anything not listed falls to the catch-all below, which
# is deliberately the cheapest tier - a plan should never silently gain access
# to the most expensive model because we forgot to name it here.
# Ordered by monthly price, which is the ladder the plans are actually sold on:
# Free $0 < Starter $29.99 < Basic $39.99 < Premium $49.99 < Ultra $99.99.
PLAN_DEFAULTS = {
    'Free':    {'models': ['luna'],                 'web_search': False},
    'Starter': {'models': ['luna'],                 'web_search': False},
    'Basic':   {'models': ['luna', 'terra'],        'web_search': False},
    'Premium': {'models': ['luna', 'terra', 'sol'], 'web_search': True},
    'Ultra':   {'models': ['luna', 'terra', 'sol'], 'web_search': True},
    'Admin':   {'models': ['luna', 'terra', 'sol'], 'web_search': True},
}
CATCH_ALL = {'models': [model_catalog.CHEAPEST_ALIAS], 'web_search': False}


def migrate_add_plan_allowed_models():
    """Add allowed_models + web_search_enabled to Plan and backfill every row."""
    app = create_app()

    with app.app_context():
        try:
            print("Starting migration: Add allowed_models and web_search_enabled to Plan...")

            print("Ensuring Phase 2 columns exist...")
            ensure_phase2_columns(db)

            print("Backfilling plans...")
            for plan in Plan.query.order_by(Plan.id).all():
                defaults = PLAN_DEFAULTS.get(plan.name)
                matched = defaults is not None
                if not matched:
                    defaults = CATCH_ALL

                if plan.allowed_models:
                    print(f"  {plan.name!r}: allowed_models already set "
                          f"({plan.allowed_models}). Leaving as is.")
                else:
                    models = model_catalog.filter_allowed(defaults['models'])
                    plan.allowed_models = json.dumps(models)
                    plan.web_search_enabled = defaults['web_search']
                    note = '' if matched else '  <-- unrecognized plan name, used catch-all'
                    print(f"  {plan.name!r}: allowed_models={models}, "
                          f"web_search_enabled={defaults['web_search']}{note}")

            db.session.commit()
            print("Migration completed successfully!")

        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()
            raise


if __name__ == '__main__':
    migrate_add_plan_allowed_models()
