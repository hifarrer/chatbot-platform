#!/usr/bin/env python3
"""
Migration script to add show_contact_sales field to Plan model.
This script adds the new boolean field to existing plans in the database.
"""

import sys
import os
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Plan

def migrate_add_contact_sales():
    """Add show_contact_sales field to Plan model."""
    app = create_app()
    
    with app.app_context():
        try:
            print("Starting migration: Add show_contact_sales field to Plan model...")
            
            # Check if the column already exists
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('plan')]
            
            if 'show_contact_sales' in columns:
                print("Column 'show_contact_sales' already exists. Skipping migration.")
                return
            
            # Add the new column
            print("Adding show_contact_sales column to plan table...")
            db.session.execute(text("ALTER TABLE plan ADD COLUMN show_contact_sales BOOLEAN DEFAULT FALSE"))
            
            # Update existing plans - set Ultra plan to show contact sales
            print("Updating existing plans...")
            ultra_plan = Plan.query.filter_by(name='Ultra').first()
            if ultra_plan:
                ultra_plan.show_contact_sales = True
                print(f"Set Ultra plan (ID: {ultra_plan.id}) to show Contact Sales button")
            
            # Commit all changes
            db.session.commit()
            print("Migration completed successfully!")
            
        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    migrate_add_contact_sales()
