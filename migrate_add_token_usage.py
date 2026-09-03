#!/usr/bin/env python3
"""
Migration: monthly token allowances and token metering.

- Plan.monthly_token_limit          (NULL / <= 0 means unlimited)
- Conversation.{prompt,completion,total}_tokens, Conversation.model_alias
- the token_usage table (created by db.create_all(), verified here)
- seeds the admin-editable 'token_limit_message' setting

Idempotent: every column is guarded independently, so a partial run resumes.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Plan, Settings, DEFAULT_TOKEN_LIMIT_MESSAGE
from migrate_phase2_common import ensure_phase2_columns

# Backfill by plan name. Admin is uncapped. Anything unrecognized gets the Free
# allowance rather than unlimited - fail closed on cost.
PLAN_TOKEN_LIMITS = {
    'Free':      100000,
    'Starter':   500000,
    'Basic':    1000000,
    'Premium':  5000000,
    'Ultra':   15000000,
    'Admin':   None,      # unlimited
}
CATCH_ALL_LIMIT = 100000


def migrate_add_token_usage():
    """Add token allowance + metering schema and backfill plan limits."""
    app = create_app()

    with app.app_context():
        try:
            print("Starting migration: token allowances and metering...")

            from sqlalchemy import text

            print("Ensuring Phase 2 columns exist...")
            ensure_phase2_columns(db)

            # create_app() already ran db.create_all(), which creates token_usage
            # if it was missing. Verify it explicitly rather than assuming.
            print("Verifying token_usage table...")
            db.create_all()
            count = db.session.execute(text("SELECT COUNT(*) FROM token_usage")).scalar()
            print(f"  token_usage table present ({count} rows).")

            print("Backfilling plan token allowances...")
            for plan in Plan.query.order_by(Plan.id).all():
                if plan.monthly_token_limit is not None:
                    print(f"  {plan.name!r}: already set ({plan.monthly_token_limit:,}). Leaving as is.")
                    continue
                matched = plan.name in PLAN_TOKEN_LIMITS
                limit = PLAN_TOKEN_LIMITS.get(plan.name, CATCH_ALL_LIMIT)
                plan.monthly_token_limit = limit
                shown = 'unlimited' if limit is None else f"{limit:,}"
                note = '' if matched else '  <-- unrecognized plan name, used catch-all'
                print(f"  {plan.name!r}: monthly_token_limit={shown}{note}")

            # Seed the over-limit message so an admin can edit it without first
            # having to trigger the default.
            if not Settings.query.filter_by(key='token_limit_message').first():
                print("Seeding 'token_limit_message' setting...")
                db.session.add(Settings(key='token_limit_message',
                                        value=DEFAULT_TOKEN_LIMIT_MESSAGE))
            else:
                print("Setting 'token_limit_message' already exists. Skipping.")

            db.session.commit()
            print("Migration completed successfully!")

        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()
            raise


if __name__ == '__main__':
    migrate_add_token_usage()
