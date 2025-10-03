#!/usr/bin/env python3
"""
Database migration script to add Settings table for admin panel
Run this to add the admin settings functionality
"""

import sqlite3
import os

def migrate_database():
    """Add Settings table to existing database"""
    
    # Check both locations for the database
    db_paths = ['chatbot_platform.db', 'instance/chatbot_platform.db']
    db_path = None
    
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            break
    
    if not db_path:
        print("No existing database found - new installations will have the Settings table automatically")
        return
    
    print("Migrating database to add Settings table...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if Settings table already exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
        if cursor.fetchone():
            print("Settings table already exists!")
            return
        
        # Create the Settings table
        print("Creating Settings table...")
        cursor.execute("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                key VARCHAR(100) UNIQUE NOT NULL,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Add some default settings
        default_settings = [
            ('homepage_chatbot_id', None),
            ('homepage_chatbot_title', 'Platform Assistant'),
            ('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        ]
        
        for key, value in default_settings:
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
        
        conn.commit()
        print("Migration completed successfully!")
        
        # Show created settings
        cursor.execute("SELECT key, value FROM settings")
        settings = cursor.fetchall()
        
        print(f"\nCreated {len(settings)} default settings:")
        for setting in settings:
            value_display = setting[1] if setting[1] else 'NULL'
            print(f"  - {setting[0]}: {value_display}")
            
    except sqlite3.Error as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()