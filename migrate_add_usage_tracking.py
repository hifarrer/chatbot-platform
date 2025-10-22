#!/usr/bin/env python3
"""
Migration script to add ChatbotUsage table for tracking where chatbots are used
"""

import os
import sys
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db

def migrate_usage_tracking():
    """Add ChatbotUsage table for tracking chatbot usage"""
    print("Starting usage tracking migration...")
    
    try:
        # Create the ChatbotUsage table
        db.create_all()
        print("Successfully created ChatbotUsage table!")
        
        # Verify the table was created
        result = db.engine.execute(db.text("SELECT COUNT(*) FROM chatbot_usage"))
        print("ChatbotUsage table is ready for tracking!")
        
    except Exception as e:
        print(f"Error creating ChatbotUsage table: {e}")

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        migrate_usage_tracking()
