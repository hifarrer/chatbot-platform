#!/usr/bin/env python3
"""
Migration script to add url_name field to existing chatbots
"""

import os
import sys
import re
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Chatbot, User

def generate_url_name(name):
    """Generate a URL-friendly name from a chatbot name"""
    # Convert to lowercase and replace spaces with hyphens
    url_name = re.sub(r'[^a-zA-Z0-9\-_]', '', name.lower().replace(' ', '-'))
    # Remove multiple consecutive hyphens
    url_name = re.sub(r'-+', '-', url_name)
    # Remove leading/trailing hyphens
    url_name = url_name.strip('-')
    return url_name

def migrate_chatbots():
    """Add url_name to existing chatbots"""
    print("Starting chatbot URL name migration...")
    
    # First, add the column if it doesn't exist
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("ALTER TABLE chatbot ADD COLUMN url_name VARCHAR(100)"))
            conn.commit()
        print("Added url_name column to chatbot table")
    except Exception as e:
        if "already exists" in str(e) or "duplicate column" in str(e).lower():
            print("url_name column already exists")
        else:
            print(f"Error adding column: {e}")
    
    # Get all chatbots without url_name
    try:
        chatbots = Chatbot.query.filter(Chatbot.url_name.is_(None)).all()
    except Exception as e:
        print(f"Error querying chatbots: {e}")
        return
    
    print(f"Found {len(chatbots)} chatbots to migrate")
    
    for i, chatbot in enumerate(chatbots, 1):
        # Generate URL name
        url_name = generate_url_name(chatbot.name)
        
        # If url_name is empty, use a fallback
        if not url_name:
            url_name = f"chatbot-{chatbot.id}"
        
        # Check for duplicates within the same user
        existing = Chatbot.query.filter_by(user_id=chatbot.user_id, url_name=url_name).first()
        if existing and existing.id != chatbot.id:
            # Add suffix to make it unique
            counter = 1
            original_url_name = url_name
            while existing:
                url_name = f"{original_url_name}-{counter}"
                existing = Chatbot.query.filter_by(user_id=chatbot.user_id, url_name=url_name).first()
                counter += 1
        
        # Update the chatbot
        chatbot.url_name = url_name
        print(f"Updated {i}/{len(chatbots)} - '{chatbot.name}' -> '{url_name}'")
    
    # Commit changes
    db.session.commit()
    print(f"Successfully migrated {len(chatbots)} chatbots!")
    
    # Verify migration
    remaining = Chatbot.query.filter(Chatbot.url_name.is_(None)).count()
    if remaining == 0:
        print("All chatbots now have URL names!")
    else:
        print(f"Warning: {remaining} chatbots still missing URL names")

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        migrate_chatbots()
