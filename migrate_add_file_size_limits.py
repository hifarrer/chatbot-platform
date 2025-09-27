#!/usr/bin/env python3
"""
Migration script to add file_size_limit_mb field to Plan model and set default values.
This script adds the new field to existing plans in the database with the specified limits:
- Free: 10MB
- Starter: 50MB  
- Premium: 100MB
- Ultra: 1GB (1024MB)
"""

import sys
import os
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Plan

def migrate_add_file_size_limits():
    """Add file_size_limit_mb field to Plan model and set default values."""
    app = create_app()
    
    with app.app_context():
        try:
            print("Starting migration: Add file_size_limit_mb field to Plan model...")
            
            # Check if the column already exists
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('plan')]
            
            if 'file_size_limit_mb' in columns:
                print("Column 'file_size_limit_mb' already exists. Skipping migration.")
                return
            
            # Add the new column
            print("Adding file_size_limit_mb column to plan table...")
            db.session.execute(text("ALTER TABLE plan ADD COLUMN file_size_limit_mb INTEGER DEFAULT 10"))
            
            # Update existing plans with their file size limits
            print("Updating existing plans with file size limits...")
            
            # Define plan limits
            plan_limits = {
                'Free': 10,
                'Starter': 50,
                'Premium': 100,
                'Ultra': 1024  # 1GB
            }
            
            for plan_name, limit_mb in plan_limits.items():
                plan = Plan.query.filter_by(name=plan_name).first()
                if plan:
                    plan.file_size_limit_mb = limit_mb
                    print(f"Set {plan_name} plan (ID: {plan.id}) file size limit to {limit_mb}MB")
                else:
                    print(f"Plan '{plan_name}' not found in database")
            
            # Commit all changes
            db.session.commit()
            print("Migration completed successfully!")
            
        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    migrate_add_file_size_limits()
