#!/usr/bin/env python3
"""
Database viewer script for the Chatbot Platform
Shows all data in the SQLite database in a readable format
"""

import sqlite3
import os
from datetime import datetime

def view_database():
    db_path = 'instance/chatbot_platform.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        print("Make sure you've run the application at least once to create the database.")
        return
    
    print("🗄️  Chatbot Platform Database Viewer")
    print("=" * 50)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Users table
        print("\n👥 USERS:")
        print("-" * 30)
        cursor.execute("SELECT id, username, email, created_at FROM user")
        users = cursor.fetchall()
        
        if users:
            for user in users:
                print(f"ID: {user[0]} | Username: {user[1]} | Email: {user[2]} | Created: {user[3]}")
        else:
            print("No users found")
        
        # Chatbots table
        print("\n🤖 CHATBOTS:")
        print("-" * 30)
        cursor.execute("""
            SELECT c.id, c.name, c.description, c.embed_code, c.is_trained, c.created_at, u.username 
            FROM chatbot c 
            LEFT JOIN user u ON c.user_id = u.id
        """)
        chatbots = cursor.fetchall()
        
        if chatbots:
            for bot in chatbots:
                trained_status = "✅ Trained" if bot[4] else "❌ Not Trained"
                print(f"ID: {bot[0]} | Name: {bot[1]} | Owner: {bot[6]} | {trained_status}")
                print(f"   Description: {bot[2]}")
                print(f"   Embed Code: {bot[3]}")
                print(f"   Created: {bot[5]}")
                print()
        else:
            print("No chatbots found")
        
        # Documents table
        print("\n📄 DOCUMENTS:")
        print("-" * 30)
        cursor.execute("""
            SELECT d.id, d.original_filename, d.processed, d.uploaded_at, c.name 
            FROM document d 
            LEFT JOIN chatbot c ON d.chatbot_id = c.id
        """)
        documents = cursor.fetchall()
        
        if documents:
            for doc in documents:
                processed_status = "✅ Processed" if doc[2] else "⏳ Pending"
                print(f"ID: {doc[0]} | File: {doc[1]} | Chatbot: {doc[4]} | {processed_status}")
                print(f"   Uploaded: {doc[3]}")
                print()
        else:
            print("No documents found")
        
        # Conversations table
        print("\n💬 RECENT CONVERSATIONS (Last 10):")
        print("-" * 30)
        cursor.execute("""
            SELECT c.user_message, c.bot_response, c.timestamp, cb.name 
            FROM conversation c 
            LEFT JOIN chatbot cb ON c.chatbot_id = cb.id 
            ORDER BY c.timestamp DESC 
            LIMIT 10
        """)
        conversations = cursor.fetchall()
        
        if conversations:
            for conv in conversations:
                print(f"Chatbot: {conv[3]} | Time: {conv[2]}")
                print(f"   User: {conv[0][:100]}{'...' if len(conv[0]) > 100 else ''}")
                print(f"   Bot:  {conv[1][:100]}{'...' if len(conv[1]) > 100 else ''}")
                print()
        else:
            print("No conversations found")
        
        # Database statistics
        print("\n📊 STATISTICS:")
        print("-" * 30)
        
        cursor.execute("SELECT COUNT(*) FROM user")
        user_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM chatbot")
        chatbot_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM chatbot WHERE is_trained = 1")
        trained_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM document")
        document_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM conversation")
        conversation_count = cursor.fetchone()[0]
        
        print(f"Users: {user_count}")
        print(f"Chatbots: {chatbot_count} ({trained_count} trained)")
        print(f"Documents: {document_count}")
        print(f"Conversations: {conversation_count}")
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
    
    finally:
        conn.close()

if __name__ == "__main__":
    view_database()