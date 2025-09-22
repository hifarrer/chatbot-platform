#!/usr/bin/env python3
"""
Simple script to run SQL INSERT statements on PostgreSQL
Usage: python run_sql_inserts.py <sql_file>
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

def run_sql_file(sql_file_path):
    """Run SQL INSERT statements from a file"""
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
        
        cursor = conn.cursor()
        
        print(f"📄 Running SQL file: {sql_file_path}")
        
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Split by semicolon and execute each statement
        statements = [stmt.strip() for stmt in sql_content.split(';') if stmt.strip()]
        
        success_count = 0
        error_count = 0
        
        for i, statement in enumerate(statements, 1):
            if not statement:
                continue
                
            try:
                print(f"   🔄 Executing statement {i}/{len(statements)}")
                cursor.execute(statement)
                success_count += 1
            except Exception as e:
                print(f"   ❌ Error in statement {i}: {e}")
                print(f"   📝 Statement: {statement[:100]}...")
                error_count += 1
                continue
        
        conn.commit()
        print(f"\n✅ SQL execution completed!")
        print(f"   Success: {success_count} statements")
        print(f"   Errors: {error_count} statements")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python run_sql_inserts.py <sql_file>")
        print("Example: python run_sql_inserts.py my_data.sql")
        sys.exit(1)
    
    sql_file = sys.argv[1]
    if not os.path.exists(sql_file):
        print(f"❌ File not found: {sql_file}")
        sys.exit(1)
    
    run_sql_file(sql_file)
