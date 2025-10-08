#!/usr/bin/env python3
"""
Migration script to add Basic and Premium plans to the database
"""

import sys
import os
import json
from datetime import datetime

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Plan

def add_plans():
    """Add Basic and Premium plans to the database"""
    app = create_app()
    
    with app.app_context():
        # Check if plans already exist
        basic_plan = Plan.query.filter_by(name='Basic').first()
        premium_plan = Plan.query.filter_by(name='Premium').first()
        
        if basic_plan and premium_plan:
            print("Basic and Premium plans already exist. Skipping migration.")
            return
        
        # Basic Plan features
        basic_features = [
            "1 AI Avatar",
            "1 Custom Knowledge Base", 
            "Up to 100 Streaming Sessions",
            "Basic Analytics",
            "Email Support",
            "API Access"
        ]
        
        # Premium Plan features
        premium_features = [
            "10 AI Avatars",
            "10 Custom Knowledge Bases",
            "Up to 1,000 Streaming Sessions", 
            "Advanced Analytics & Insights",
            "Priority Support",
            "White-label Options"
        ]
        
        # Create Basic Plan
        if not basic_plan:
            basic_plan = Plan(
                name='Basic',
                description='Perfect for small businesses and individuals getting started with AI chatbots',
                monthly_price=39.0,
                yearly_price=390.0,
                chatbot_limit=1,
                file_size_limit_mb=50,
                features=json.dumps(basic_features),
                is_active=True,
                show_contact_sales=False,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.session.add(basic_plan)
            print("[OK] Added Basic plan")
        else:
            print("[INFO] Basic plan already exists")
        
        # Create Premium Plan
        if not premium_plan:
            premium_plan = Plan(
                name='Premium',
                description='Advanced features for growing businesses and enterprises',
                monthly_price=99.0,
                yearly_price=990.0,
                chatbot_limit=10,
                file_size_limit_mb=200,
                features=json.dumps(premium_features),
                is_active=True,
                show_contact_sales=False,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.session.add(premium_plan)
            print("[OK] Added Premium plan")
        else:
            print("[INFO] Premium plan already exists")
        
        # Commit changes
        try:
            db.session.commit()
            print("[SUCCESS] Plans migration completed successfully!")
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Error adding plans: {e}")
            raise

if __name__ == '__main__':
    add_plans()
