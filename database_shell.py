#!/usr/bin/env python3
"""
Interactive database shell for the Chatbot Platform
Allows you to run SQL queries directly on the PostgreSQL database
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
import sys
from dotenv import load_dotenv

def database_shell():
    print("🗄️  Chatbot Platform PostgreSQL Database Shell")
    print("Type SQL queries or 'help' for commands, 'exit' to quit")
    print("=" * 50)
    
    try:
        # Load environment variables
        load_dotenv()
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host=os.environ.get('PGHOST'),
            database=os.environ.get('PGDATABASE'),
            user=os.environ.get('PGUSER'),
            password=os.environ.get('PGPASSWORD'),
            port=os.environ.get('PGPORT', 5432)
        )
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
    
        while True:
            query = input("\nSQL> ").strip()
            
            if query.lower() in ['exit', 'quit', 'q']:
                break
            elif query.lower() == 'help':
                print_help()
                continue
            elif query.lower() == 'tables':
                show_tables(cursor)
                continue
            elif query.lower().startswith('desc '):
                table_name = query[5:].strip()
                describe_table(cursor, table_name)
                continue
            elif not query:
                continue
            
            try:
                cursor.execute(query)
                
                if query.lower().startswith('select'):
                    results = cursor.fetchall()
                    if results:
                        # Print column headers
                        headers = list(results[0].keys())
                        print(" | ".join(f"{h:15}" for h in headers))
                        print("-" * (len(headers) * 17))
                        
                        # Print rows
                        for row in results:
                            print(" | ".join(f"{str(row[h])[:15]:15}" for h in headers))
                    else:
                        print("No results found")
                else:
                    conn.commit()
                    print(f"Query executed successfully. Rows affected: {cursor.rowcount}")
                    
            except psycopg2.Error as e:
                print(f"❌ SQL Error: {e}")
    
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
    except Exception as e:
        print(f"❌ Connection Error: {e}")
    
    finally:
        if 'conn' in locals():
            conn.close()

def print_help():
    print("""
Available commands:
- help          : Show this help
- tables        : List all tables
- desc <table>  : Describe table structure
- exit/quit/q   : Exit the shell

Example queries:
- SELECT * FROM user;
- SELECT name, is_trained FROM chatbot;
- SELECT COUNT(*) FROM conversation;
- SELECT * FROM conversation ORDER BY timestamp DESC LIMIT 5;
""")

def show_tables(cursor):
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    tables = cursor.fetchall()
    print("\nTables in database:")
    for table in tables:
        print(f"  - {table['table_name']}")

def describe_table(cursor, table_name):
    try:
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = %s AND table_schema = 'public'
            ORDER BY ordinal_position
        """, (table_name,))
        columns = cursor.fetchall()
        if columns:
            print(f"\nStructure of table '{table_name}':")
            print("Column Name      | Type         | Not Null | Default")
            print("-" * 55)
            for col in columns:
                null_str = "YES" if col['is_nullable'] == 'YES' else "NO"
                default_str = str(col['column_default']) if col['column_default'] is not None else "NULL"
                print(f"{col['column_name']:15} | {col['data_type']:12} | {null_str:8} | {default_str}")
        else:
            print(f"Table '{table_name}' not found")
    except psycopg2.Error as e:
        print(f"❌ Error describing table: {e}")

if __name__ == "__main__":
    database_shell()