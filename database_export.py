#!/usr/bin/env python3
"""
Database export utility for the chatbot platform.
Exports the entire database as SQL statements with schema and data.
"""

import sqlite3
import os
from datetime import datetime

def export_database_to_sql(db_path=None, output_path=None):
    """
    Export the entire database to SQL statements including schema and data.
    
    Args:
        db_path (str): Path to the database file. If None, will try to find it.
        output_path (str): Path where to save the SQL file. If None, will generate a timestamped filename.
    
    Returns:
        str: Path to the exported SQL file
    """
    
    # Find database path if not provided
    if not db_path:
        possible_paths = [
            'chatbot_platform.db',
            'instance/chatbot_platform.db',
            'instance/chatbot_platform.db'
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                db_path = path
                break
        
        if not db_path:
            raise FileNotFoundError("Database file not found")
    
    # Generate output path if not provided
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"database_backup_{timestamp}.sql"
    
    print(f"Exporting database from: {db_path}")
    print(f"Output file: {output_path}")
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header
            f.write("-- Database Backup\n")
            f.write(f"-- Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"-- Source database: {db_path}\n")
            f.write("-- This file contains the complete database schema and data\n\n")
            
            # Get all table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = cursor.fetchall()
            
            f.write("-- ==============================================\n")
            f.write("-- SCHEMA DEFINITIONS\n")
            f.write("-- ==============================================\n\n")
            
            # Export schema for each table
            for table_name, in tables:
                f.write(f"-- Table: {table_name}\n")
                
                # Get CREATE TABLE statement
                cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                create_sql = cursor.fetchone()
                
                if create_sql and create_sql[0]:
                    f.write(f"{create_sql[0]};\n\n")
                else:
                    f.write(f"-- No schema found for table {table_name}\n\n")
            
            f.write("-- ==============================================\n")
            f.write("-- DATA EXPORT\n")
            f.write("-- ==============================================\n\n")
            
            # Export data for each table
            for table_name, in tables:
                f.write(f"-- Data for table: {table_name}\n")
                
                # Get table info
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                
                if not columns:
                    f.write(f"-- No columns found for table {table_name}\n\n")
                    continue
                
                # Get all data from table
                cursor.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()
                
                if not rows:
                    f.write(f"-- No data in table {table_name}\n\n")
                    continue
                
                # Get column names
                column_names = [col[1] for col in columns]
                
                # Write INSERT statements
                for row in rows:
                    # Escape single quotes in data
                    escaped_row = []
                    for value in row:
                        if value is None:
                            escaped_row.append('NULL')
                        elif isinstance(value, str):
                            # Escape single quotes and wrap in quotes
                            escaped_value = value.replace("'", "''")
                            escaped_row.append(f"'{escaped_value}'")
                        else:
                            escaped_row.append(str(value))
                    
                    # Create INSERT statement
                    columns_str = ', '.join(column_names)
                    values_str = ', '.join(escaped_row)
                    f.write(f"INSERT INTO {table_name} ({columns_str}) VALUES ({values_str});\n")
                
                f.write("\n")
            
            f.write("-- ==============================================\n")
            f.write("-- BACKUP COMPLETE\n")
            f.write("-- ==============================================\n")
        
        print(f"Database exported successfully to: {output_path}")
        return output_path
        
    except Exception as e:
        print(f"Error exporting database: {e}")
        raise
    finally:
        conn.close()

def get_database_info(db_path=None):
    """
    Get information about the database (tables, row counts, etc.)
    
    Args:
        db_path (str): Path to the database file
    
    Returns:
        dict: Database information
    """
    if not db_path:
        possible_paths = [
            'chatbot_platform.db',
            'instance/chatbot_platform.db'
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                db_path = path
                break
    
    if not db_path or not os.path.exists(db_path):
        return {"error": "Database not found"}
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        
        # Get row counts for each table
        table_info = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            table_info[table] = count
        
        # Get database file size
        file_size = os.path.getsize(db_path)
        
        return {
            "database_path": db_path,
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "tables": tables,
            "table_counts": table_info,
            "total_tables": len(tables),
            "total_records": sum(table_info.values())
        }
        
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()

if __name__ == "__main__":
    # Test the export functionality
    try:
        info = get_database_info()
        if "error" in info:
            print(f"Database info: {info}")
        else:
            print(f"Database info: {info}")
            
            export_path = export_database_to_sql()
            print(f"Export completed: {export_path}")
    except Exception as e:
        print(f"Error: {e}")
