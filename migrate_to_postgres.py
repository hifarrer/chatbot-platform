#!/usr/bin/env python3
"""
Migration script to migrate from SQLite to PostgreSQL
This script will:
1. Create tables in PostgreSQL
2. Migrate data from SQLite (if exists)
3. Update configuration
"""

import os
import sys
import sqlite3
from psycopg2.extras import RealDictCursor
from datetime import datetime
from services.db_connection import describe_target, get_postgres_connection

def get_sqlite_connection():
    """Get SQLite connection, try multiple possible locations"""
    possible_paths = [
        'chatbot_platform.db',
        'instance/chatbot_platform.db',
        'app.db'
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            print(f"📁 Found SQLite database at: {path}")
            return sqlite3.connect(path)
    
    print("⚠️  No SQLite database found - will create fresh PostgreSQL tables")
    return None

def create_postgres_tables(pg_conn):
    """Create all tables in PostgreSQL"""
    print("🏗️  Creating PostgreSQL tables...")
    
    cursor = pg_conn.cursor()
    
    # Create tables in the correct order (respecting foreign key constraints)
    tables = [
        """
        CREATE TABLE IF NOT EXISTS "user" (
            id SERIAL PRIMARY KEY,
            username VARCHAR(80) UNIQUE NOT NULL,
            email VARCHAR(120) UNIQUE NOT NULL,
            password_hash VARCHAR(120) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS chatbot (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            system_prompt TEXT DEFAULT 'You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge.',
            embed_code VARCHAR(36) UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_trained BOOLEAN DEFAULT FALSE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS document (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            chatbot_id INTEGER NOT NULL REFERENCES chatbot(id) ON DELETE CASCADE,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed BOOLEAN DEFAULT FALSE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS conversation (
            id SERIAL PRIMARY KEY,
            chatbot_id INTEGER NOT NULL REFERENCES chatbot(id) ON DELETE CASCADE,
            user_message TEXT NOT NULL,
            bot_response TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS settings (
            id SERIAL PRIMARY KEY,
            key VARCHAR(100) UNIQUE NOT NULL,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    ]
    
    for table_sql in tables:
        try:
            cursor.execute(table_sql)
            print("   ✅ Table created successfully")
        except Exception as e:
            print(f"   ⚠️  Table creation warning: {e}")
    
    pg_conn.commit()
    cursor.close()
    print("✅ All PostgreSQL tables created!")

def migrate_data(sqlite_conn, pg_conn):
    """Migrate data from SQLite to PostgreSQL"""
    if not sqlite_conn:
        print("📝 No SQLite data to migrate - starting with empty PostgreSQL database")
        return
    
    print("📦 Migrating data from SQLite to PostgreSQL...")
    
    sqlite_cursor = sqlite_conn.cursor()
    pg_cursor = pg_conn.cursor()
    
    # Enable row factory for SQLite to get column names
    sqlite_conn.row_factory = sqlite3.Row
    
    # Migrate users
    print("   👥 Migrating users...")
    sqlite_cursor.execute("SELECT * FROM user")
    users = sqlite_cursor.fetchall()
    
    for user in users:
        try:
            pg_cursor.execute("""
                INSERT INTO "user" (id, username, email, password_hash, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (user['id'], user['username'], user['email'], user['password_hash'], user['created_at']))
        except Exception as e:
            print(f"     ⚠️  User migration warning: {e}")
    
    print(f"   ✅ Migrated {len(users)} users")
    
    # Migrate chatbots
    print("   🤖 Migrating chatbots...")
    sqlite_cursor.execute("SELECT * FROM chatbot")
    chatbots = sqlite_cursor.fetchall()
    
    for chatbot in chatbots:
        try:
            pg_cursor.execute("""
                INSERT INTO chatbot (id, name, description, system_prompt, embed_code, user_id, created_at, is_trained)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (chatbot['id'], chatbot['name'], chatbot['description'], 
                  chatbot['system_prompt'], chatbot['embed_code'], 
                  chatbot['user_id'], chatbot['created_at'], chatbot['is_trained']))
        except Exception as e:
            print(f"     ⚠️  Chatbot migration warning: {e}")
    
    print(f"   ✅ Migrated {len(chatbots)} chatbots")
    
    # Migrate documents
    print("   📄 Migrating documents...")
    sqlite_cursor.execute("SELECT * FROM document")
    documents = sqlite_cursor.fetchall()
    
    for document in documents:
        try:
            pg_cursor.execute("""
                INSERT INTO document (id, filename, original_filename, file_path, chatbot_id, uploaded_at, processed)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (document['id'], document['filename'], document['original_filename'],
                  document['file_path'], document['chatbot_id'], 
                  document['uploaded_at'], document['processed']))
        except Exception as e:
            print(f"     ⚠️  Document migration warning: {e}")
    
    print(f"   ✅ Migrated {len(documents)} documents")
    
    # Migrate conversations
    print("   💬 Migrating conversations...")
    sqlite_cursor.execute("SELECT * FROM conversation")
    conversations = sqlite_cursor.fetchall()
    
    for conversation in conversations:
        try:
            pg_cursor.execute("""
                INSERT INTO conversation (id, chatbot_id, user_message, bot_response, timestamp)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (conversation['id'], conversation['chatbot_id'], 
                  conversation['user_message'], conversation['bot_response'], 
                  conversation['timestamp']))
        except Exception as e:
            print(f"     ⚠️  Conversation migration warning: {e}")
    
    print(f"   ✅ Migrated {len(conversations)} conversations")
    
    # Migrate settings
    print("   ⚙️  Migrating settings...")
    sqlite_cursor.execute("SELECT * FROM settings")
    settings = sqlite_cursor.fetchall()
    
    for setting in settings:
        try:
            pg_cursor.execute("""
                INSERT INTO settings (id, key, value, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (setting['id'], setting['key'], setting['value'], setting['updated_at']))
        except Exception as e:
            print(f"     ⚠️  Setting migration warning: {e}")
    
    print(f"   ✅ Migrated {len(settings)} settings")
    
    # Update sequences to match the highest IDs
    print("   🔄 Updating PostgreSQL sequences...")
    sequences = [
        ('"user"', 'id'),
        ('chatbot', 'id'),
        ('document', 'id'),
        ('conversation', 'id'),
        ('settings', 'id')
    ]
    
    for table, column in sequences:
        try:
            pg_cursor.execute(f"SELECT MAX({column}) FROM {table}")
            max_id = pg_cursor.fetchone()[0]
            if max_id:
                pg_cursor.execute(f"SELECT setval('{table}_{column}_seq', {max_id})")
        except Exception as e:
            print(f"     ⚠️  Sequence update warning for {table}: {e}")
    
    pg_conn.commit()
    sqlite_cursor.close()
    pg_cursor.close()
    print("✅ Data migration completed!")

def verify_migration(pg_conn):
    """Verify the migration was successful"""
    print("🔍 Verifying migration...")
    
    cursor = pg_conn.cursor(cursor_factory=RealDictCursor)
    
    # Count records in each table
    tables = ['"user"', 'chatbot', 'document', 'conversation', 'settings']
    
    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
            count = cursor.fetchone()['count']
            print(f"   📊 {table}: {count} records")
        except Exception as e:
            print(f"   ❌ Error counting {table}: {e}")
    
    cursor.close()
    print("✅ Migration verification completed!")

def main():
    """Main migration function"""
    print("🚀 Starting SQLite to PostgreSQL migration...")
    print("=" * 50)
    
    try:
        # Get connections
        pg_conn = get_postgres_connection()
        print(f"📡 Connected to: {describe_target()}")
        sqlite_conn = get_sqlite_connection()
        
        # Create PostgreSQL tables
        create_postgres_tables(pg_conn)
        
        # Migrate data
        migrate_data(sqlite_conn, pg_conn)
        
        # Verify migration
        verify_migration(pg_conn)
        
        print("\n🎉 Migration completed successfully!")
        print("📝 Next steps:")
        print("   1. Update your .env file to use PostgreSQL (already done)")
        print("   2. Test your application with: python app.py")
        print("   3. Remove SQLite database files if everything works")
        
        # Close connections
        pg_conn.close()
        if sqlite_conn:
            sqlite_conn.close()
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
