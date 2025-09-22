#!/usr/bin/env python3
"""
Database viewer script for the Chatbot Platform
Shows all data in the PostgreSQL database in a readable format
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime
from dotenv import load_dotenv

def view_database():
    print("🗄️  Chatbot Platform PostgreSQL Database Viewer")
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
    
        # Users table
        print("\n👥 USERS:")
        print("-" * 30)
        cursor.execute('SELECT id, username, email, created_at FROM "user"')
        users = cursor.fetchall()
        
        if users:
            for user in users:
                print(f"ID: {user['id']} | Username: {user['username']} | Email: {user['email']} | Created: {user['created_at']}")
        else:
            print("No users found")
        
        # Chatbots table
        print("\n🤖 CHATBOTS:")
        print("-" * 30)
        cursor.execute("""
            SELECT c.id, c.name, c.description, c.embed_code, c.is_trained, c.created_at, u.username 
            FROM chatbot c 
            LEFT JOIN "user" u ON c.user_id = u.id
        """)
        chatbots = cursor.fetchall()
        
        if chatbots:
            for bot in chatbots:
                trained_status = "✅ Trained" if bot['is_trained'] else "❌ Not Trained"
                print(f"ID: {bot['id']} | Name: {bot['name']} | Owner: {bot['username']} | {trained_status}")
                print(f"   Description: {bot['description']}")
                print(f"   Embed Code: {bot['embed_code']}")
                print(f"   Created: {bot['created_at']}")
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
                processed_status = "✅ Processed" if doc['processed'] else "⏳ Pending"
                print(f"ID: {doc['id']} | File: {doc['original_filename']} | Chatbot: {doc['name']} | {processed_status}")
                print(f"   Uploaded: {doc['uploaded_at']}")
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
                print(f"Chatbot: {conv['name']} | Time: {conv['timestamp']}")
                print(f"   User: {conv['user_message'][:100]}{'...' if len(conv['user_message']) > 100 else ''}")
                print(f"   Bot:  {conv['bot_response'][:100]}{'...' if len(conv['bot_response']) > 100 else ''}")
                print()
        else:
            print("No conversations found")
        
        # Database statistics
        print("\n📊 STATISTICS:")
        print("-" * 30)
        
        cursor.execute('SELECT COUNT(*) FROM "user"')
        user_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM chatbot")
        chatbot_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM chatbot WHERE is_trained = true")
        trained_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM document")
        document_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM conversation")
        conversation_count = cursor.fetchone()['count']
        
        print(f"Users: {user_count}")
        print(f"Chatbots: {chatbot_count} ({trained_count} trained)")
        print(f"Documents: {document_count}")
        print(f"Conversations: {conversation_count}")
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    view_database()