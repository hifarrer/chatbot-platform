#!/usr/bin/env python3
"""
Migration script to add FAQ table and populate with default questions
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def get_database_url():
    """Get database URL from environment variables"""
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///chatbot_platform.db')
    
    # Handle PostgreSQL URL for compatibility
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    return database_url

def create_faq_table():
    """Create the FAQ table"""
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    with engine.connect() as conn:
        # Create FAQ table
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS faq (
            id SERIAL PRIMARY KEY,
            question VARCHAR(500) NOT NULL,
            answer TEXT NOT NULL,
            "order" INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # For SQLite, use different syntax
        if database_url.startswith('sqlite'):
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS faq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question VARCHAR(500) NOT NULL,
                answer TEXT NOT NULL,
                "order" INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        
        conn.execute(text(create_table_sql))
        conn.commit()
        print("✅ FAQ table created successfully")

def populate_default_faqs():
    """Populate the FAQ table with default questions"""
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    # Default FAQ questions
    default_faqs = [
        {
            'question': 'How much does the ChatBot Platform cost?',
            'answer': 'The platform itself is free to use! You only need an OpenAI API key for GPT responses, which costs approximately $0.002 per 1000 tokens (very affordable for most use cases).',
            'order': 1
        },
        {
            'question': 'What file formats can I upload for training?',
            'answer': 'You can upload PDF, DOCX (Word documents), and TXT files. The platform automatically processes these documents to train your chatbot with your content.',
            'order': 2
        },
        {
            'question': 'How do I embed the chatbot on my website?',
            'answer': 'After creating and training your chatbot, you\'ll get a simple HTML embed code. Just copy and paste it into your website\'s HTML, and the chatbot will appear as a floating widget in the bottom-right corner.',
            'order': 3
        },
        {
            'question': 'Can I create multiple chatbots?',
            'answer': 'Yes! You can create unlimited chatbots for different purposes, websites, or departments. Each chatbot can be trained with different documents and have its own unique knowledge base.',
            'order': 4
        }
    ]
    
    with engine.connect() as conn:
        # Check if FAQ table already has data
        result = conn.execute(text("SELECT COUNT(*) FROM faq"))
        count = result.scalar()
        
        if count == 0:
            # Insert default FAQ questions
            for faq in default_faqs:
                insert_sql = """
                INSERT INTO faq (question, answer, "order", is_active, created_at, updated_at)
                VALUES (:question, :answer, :order, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
                conn.execute(text(insert_sql), faq)
            
            conn.commit()
            print(f"✅ Added {len(default_faqs)} default FAQ questions")
        else:
            print(f"ℹ️ FAQ table already contains {count} questions, skipping default population")

def main():
    """Main migration function"""
    print("🚀 Starting FAQ migration...")
    
    try:
        # Create FAQ table
        create_faq_table()
        
        # Populate with default questions
        populate_default_faqs()
        
        print("✅ FAQ migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
