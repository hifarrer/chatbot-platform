#!/usr/bin/env python3
"""
Comprehensive data migration script for PostgreSQL
This script can:
1. Migrate from SQLite database file
2. Execute SQL INSERT statements from a file
3. Create sample data for testing
"""

import os
import sys
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from datetime import datetime
import json

def get_postgres_connection():
    """Get PostgreSQL connection using environment variables"""
    load_dotenv()
    
    return psycopg2.connect(
        host=os.environ.get('PGHOST'),
        database=os.environ.get('PGDATABASE'),
        user=os.environ.get('PGUSER'),
        password=os.environ.get('PGPASSWORD'),
        port=os.environ.get('PGPORT', 5432)
    )

def migrate_from_sqlite_file(sqlite_path, pg_conn):
    """Migrate data from a specific SQLite file"""
    if not os.path.exists(sqlite_path):
        print(f"❌ SQLite file not found: {sqlite_path}")
        return False
    
    print(f"📦 Migrating data from SQLite file: {sqlite_path}")
    
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all tables from SQLite
        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in sqlite_cursor.fetchall()]
        
        print(f"📋 Found tables: {tables}")
        
        # Migrate each table
        for table in tables:
            if table == 'sqlite_sequence':
                continue
                
            print(f"   📄 Migrating table: {table}")
            
            # Get all data from SQLite table
            sqlite_cursor.execute(f"SELECT * FROM {table}")
            rows = sqlite_cursor.fetchall()
            
            if not rows:
                print(f"     ⚠️  No data in {table}")
                continue
            
            # Get column names
            columns = list(rows[0].keys())
            placeholders = ', '.join(['%s'] * len(columns))
            column_names = ', '.join([f'"{col}"' if col == 'user' else col for col in columns])
            
            # Clear existing data in PostgreSQL table
            pg_cursor.execute(f'DELETE FROM "{table}"' if table == 'user' else f'DELETE FROM {table}')
            
            # Insert data
            for row in rows:
                values = [row[col] for col in columns]
                try:
                    pg_cursor.execute(f'INSERT INTO "{table}" ({column_names}) VALUES ({placeholders})' if table == 'user' else f'INSERT INTO {table} ({column_names}) VALUES ({placeholders})', values)
                except Exception as e:
                    print(f"     ⚠️  Error inserting row: {e}")
                    continue
            
            print(f"     ✅ Migrated {len(rows)} rows to {table}")
        
        pg_conn.commit()
        print("✅ SQLite migration completed!")
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        pg_conn.rollback()
        return False
    finally:
        sqlite_cursor.close()
        sqlite_conn.close()
        pg_cursor.close()

def execute_sql_file(sql_file_path, pg_conn):
    """Execute SQL INSERT statements from a file"""
    if not os.path.exists(sql_file_path):
        print(f"❌ SQL file not found: {sql_file_path}")
        return False
    
    print(f"📄 Executing SQL file: {sql_file_path}")
    
    cursor = pg_conn.cursor()
    
    try:
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Split by semicolon and execute each statement
        statements = [stmt.strip() for stmt in sql_content.split(';') if stmt.strip()]
        
        for i, statement in enumerate(statements, 1):
            if not statement:
                continue
                
            try:
                print(f"   🔄 Executing statement {i}/{len(statements)}")
                cursor.execute(statement)
            except Exception as e:
                print(f"   ⚠️  Error in statement {i}: {e}")
                print(f"   📝 Statement: {statement[:100]}...")
                continue
        
        pg_conn.commit()
        print("✅ SQL file execution completed!")
        return True
        
    except Exception as e:
        print(f"❌ SQL execution failed: {e}")
        pg_conn.rollback()
        return False
    finally:
        cursor.close()

def create_sample_data(pg_conn):
    """Create sample data for testing"""
    print("🎭 Creating sample data...")
    
    cursor = pg_conn.cursor()
    
    try:
        # Create sample user
        cursor.execute("""
            INSERT INTO "user" (username, email, password_hash, created_at)
            VALUES ('demo_user', 'demo@example.com', 'demo_hash', CURRENT_TIMESTAMP)
            ON CONFLICT (username) DO NOTHING
        """)
        
        # Get user ID
        cursor.execute('SELECT id FROM "user" WHERE username = %s', ('demo_user',))
        user_id = cursor.fetchone()[0]
        
        # Create sample chatbot
        cursor.execute("""
            INSERT INTO chatbot (name, description, system_prompt, embed_code, user_id, created_at, is_trained)
            VALUES ('Sample Chatbot', 'A sample chatbot for testing', 'You are a helpful assistant.', 'sample-embed-123', %s, CURRENT_TIMESTAMP, true)
            ON CONFLICT (embed_code) DO NOTHING
        """, (user_id,))
        
        # Get chatbot ID
        cursor.execute('SELECT id FROM chatbot WHERE embed_code = %s', ('sample-embed-123',))
        chatbot_id = cursor.fetchone()[0]
        
        # Create sample document
        cursor.execute("""
            INSERT INTO document (filename, original_filename, file_path, chatbot_id, uploaded_at, processed)
            VALUES ('sample_doc.txt', 'sample.txt', '/uploads/sample_doc.txt', %s, CURRENT_TIMESTAMP, true)
        """, (chatbot_id,))
        
        # Create sample conversations
        sample_conversations = [
            ('Hello!', 'Hi there! How can I help you today?'),
            ('What can you do?', 'I can answer questions and help with various tasks.'),
            ('Tell me about the platform', 'This is a chatbot platform that allows you to create AI assistants.')
        ]
        
        for user_msg, bot_resp in sample_conversations:
            cursor.execute("""
                INSERT INTO conversation (chatbot_id, user_message, bot_response, timestamp)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            """, (chatbot_id, user_msg, bot_resp))
        
        # Create sample settings
        cursor.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES ('homepage_chatbot_id', %s, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO NOTHING
        """, (str(chatbot_id),))
        
        pg_conn.commit()
        print("✅ Sample data created successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Sample data creation failed: {e}")
        pg_conn.rollback()
        return False
    finally:
        cursor.close()

def generate_insert_statements(pg_conn):
    """Generate INSERT statements for all current data"""
    print("📝 Generating INSERT statements...")
    
    cursor = pg_conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        tables = ['"user"', 'chatbot', 'document', 'conversation', 'settings']
        insert_statements = []
        
        for table in tables:
            cursor.execute(f'SELECT * FROM {table}')
            rows = cursor.fetchall()
            
            if not rows:
                continue
            
            # Get column names
            columns = list(rows[0].keys())
            column_names = ', '.join([f'"{col}"' if col == 'user' else col for col in columns])
            
            for row in rows:
                values = []
                for col in columns:
                    value = row[col]
                    if value is None:
                        values.append('NULL')
                    elif isinstance(value, str):
                        # Escape single quotes
                        escaped_value = value.replace("'", "''")
                        values.append(f"'{escaped_value}'")
                    elif isinstance(value, bool):
                        values.append('true' if value else 'false')
                    else:
                        values.append(str(value))
                
                values_str = ', '.join(values)
                insert_stmt = f'INSERT INTO {table} ({column_names}) VALUES ({values_str});'
                insert_statements.append(insert_stmt)
        
        # Write to file
        with open('postgres_insert_statements.sql', 'w', encoding='utf-8') as f:
            f.write('-- PostgreSQL INSERT statements generated on ' + str(datetime.now()) + '\n\n')
            for stmt in insert_statements:
                f.write(stmt + '\n')
        
        print(f"✅ Generated {len(insert_statements)} INSERT statements in 'postgres_insert_statements.sql'")
        return True
        
    except Exception as e:
        print(f"❌ Failed to generate INSERT statements: {e}")
        return False
    finally:
        cursor.close()

def main():
    """Main function with interactive menu"""
    print("🚀 PostgreSQL Data Migration Tool")
    print("=" * 50)
    
    try:
        pg_conn = get_postgres_connection()
        print("✅ Connected to PostgreSQL")
        
        while True:
            print("\n📋 Choose an option:")
            print("1. Migrate from SQLite database file")
            print("2. Execute SQL INSERT statements from file")
            print("3. Create sample data for testing")
            print("4. Generate INSERT statements for current data")
            print("5. View current data")
            print("6. Exit")
            
            choice = input("\nEnter your choice (1-6): ").strip()
            
            if choice == '1':
                sqlite_path = input("Enter path to SQLite database file: ").strip()
                migrate_from_sqlite_file(sqlite_path, pg_conn)
                
            elif choice == '2':
                sql_file = input("Enter path to SQL file with INSERT statements: ").strip()
                execute_sql_file(sql_file, pg_conn)
                
            elif choice == '3':
                create_sample_data(pg_conn)
                
            elif choice == '4':
                generate_insert_statements(pg_conn)
                
            elif choice == '5':
                from view_database import view_database
                view_database()
                
            elif choice == '6':
                print("👋 Goodbye!")
                break
                
            else:
                print("❌ Invalid choice. Please try again.")
        
        pg_conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
