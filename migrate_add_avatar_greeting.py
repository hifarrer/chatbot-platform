#!/usr/bin/env python3
"""
Migration script to add avatar_filename and greeting_message fields to the chatbot table.
This script handles both SQLite and PostgreSQL databases.
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

def get_database_url():
    """Get database URL from environment or use default SQLite"""
    # Load environment variables from .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///chatbot_platform.db')
    
    # Handle PostgreSQL URL for Render.com
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    return database_url

def migrate_database():
    """Add avatar_filename and greeting_message columns to chatbot table"""
    database_url = get_database_url()
    
    print(f"🔄 Starting migration for database: {database_url}")
    
    try:
        # Create engine
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Check if columns already exist
            if 'sqlite' in database_url:
                # SQLite check
                result = conn.execute(text("PRAGMA table_info(chatbot)"))
                columns = [row[1] for row in result.fetchall()]
                
                if 'avatar_filename' not in columns:
                    print("📝 Adding avatar_filename column to chatbot table...")
                    conn.execute(text("ALTER TABLE chatbot ADD COLUMN avatar_filename VARCHAR(255)"))
                    conn.commit()
                    print("✅ avatar_filename column added successfully")
                else:
                    print("ℹ️  avatar_filename column already exists")
                
                if 'greeting_message' not in columns:
                    print("📝 Adding greeting_message column to chatbot table...")
                    conn.execute(text("ALTER TABLE chatbot ADD COLUMN greeting_message VARCHAR(500)"))
                    conn.commit()
                    print("✅ greeting_message column added successfully")
                else:
                    print("ℹ️  greeting_message column already exists")
                    
            else:
                # PostgreSQL check
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'chatbot' AND column_name IN ('avatar_filename', 'greeting_message')
                """))
                existing_columns = [row[0] for row in result.fetchall()]
                
                if 'avatar_filename' not in existing_columns:
                    print("📝 Adding avatar_filename column to chatbot table...")
                    conn.execute(text("ALTER TABLE chatbot ADD COLUMN avatar_filename VARCHAR(255)"))
                    conn.commit()
                    print("✅ avatar_filename column added successfully")
                else:
                    print("ℹ️  avatar_filename column already exists")
                
                if 'greeting_message' not in existing_columns:
                    print("📝 Adding greeting_message column to chatbot table...")
                    conn.execute(text("ALTER TABLE chatbot ADD COLUMN greeting_message VARCHAR(500)"))
                    conn.commit()
                    print("✅ greeting_message column added successfully")
                else:
                    print("ℹ️  greeting_message column already exists")
            
            print("🎉 Migration completed successfully!")
            
    except SQLAlchemyError as e:
        print(f"❌ Database migration failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error during migration: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate_database()
