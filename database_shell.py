#!/usr/bin/env python3
"""
Interactive database shell for the Chatbot Platform
Allows you to run SQL queries directly on the database
"""

import sqlite3
import os
import sys

def database_shell():
    db_path = 'chatbot_platform.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        print("Make sure you've run the application at least once to create the database.")
        return
    
    print("🗄️  Chatbot Platform Database Shell")
    print("Type SQL queries or 'help' for commands, 'exit' to quit")
    print("=" * 50)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Enable headers and better formatting
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
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
                        headers = [description[0] for description in cursor.description]
                        print(" | ".join(f"{h:15}" for h in headers))
                        print("-" * (len(headers) * 17))
                        
                        # Print rows
                        for row in results:
                            print(" | ".join(f"{str(cell)[:15]:15}" for cell in row))
                    else:
                        print("No results found")
                else:
                    conn.commit()
                    print(f"Query executed successfully. Rows affected: {cursor.rowcount}")
                    
            except sqlite3.Error as e:
                print(f"❌ SQL Error: {e}")
    
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
    
    finally:
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
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("\nTables in database:")
    for table in tables:
        print(f"  - {table[0]}")

def describe_table(cursor, table_name):
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        if columns:
            print(f"\nStructure of table '{table_name}':")
            print("Column Name      | Type         | Not Null | Default")
            print("-" * 55)
            for col in columns:
                null_str = "YES" if col[3] else "NO"
                default_str = str(col[4]) if col[4] is not None else "NULL"
                print(f"{col[1]:15} | {col[2]:12} | {null_str:8} | {default_str}")
        else:
            print(f"Table '{table_name}' not found")
    except sqlite3.Error as e:
        print(f"❌ Error describing table: {e}")

if __name__ == "__main__":
    database_shell()