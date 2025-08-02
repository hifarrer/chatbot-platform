#!/usr/bin/env python3
"""
Database migration script to add system_prompt column to existing chatbots
Run this if you have existing chatbots in your database
"""

import sqlite3
import os

def migrate_database():
    """Add system_prompt column to existing database"""
    
    # Check both locations for the database
    db_paths = ['chatbot_platform.db', 'instance/chatbot_platform.db']
    db_path = None
    
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            break
    
    if not db_path:
        print("✅ No existing database found - new installations will have the system_prompt column automatically")
        return
    
    print("🗄️  Migrating database to add system_prompt column...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if system_prompt column already exists
        cursor.execute("PRAGMA table_info(chatbot)")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'system_prompt' in column_names:
            print("✅ system_prompt column already exists!")
            return
        
        # Add the system_prompt column
        print("📝 Adding system_prompt column...")
        cursor.execute("""
            ALTER TABLE chatbot 
            ADD COLUMN system_prompt TEXT DEFAULT 'You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge.'
        """)
        
        # Update existing chatbots with default prompt
        cursor.execute("""
            UPDATE chatbot 
            SET system_prompt = 'You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge.'
            WHERE system_prompt IS NULL
        """)
        
        conn.commit()
        print("✅ Migration completed successfully!")
        
        # Show updated chatbots
        cursor.execute("SELECT id, name, system_prompt FROM chatbot")
        chatbots = cursor.fetchall()
        
        print(f"\n📊 Updated {len(chatbots)} chatbot(s):")
        for chatbot in chatbots:
            print(f"  - ID {chatbot[0]}: {chatbot[1]} (prompt: {chatbot[2][:50]}...)")
            
    except sqlite3.Error as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
    
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()