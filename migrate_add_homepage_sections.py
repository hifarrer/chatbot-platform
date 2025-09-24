#!/usr/bin/env python3
"""
Migration script to add HomepageSection table and populate with default content
"""

import os
import sys
import json
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

def create_homepage_sections_table():
    """Create the HomepageSection table"""
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    with engine.connect() as conn:
        # Create HomepageSection table
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS homepage_section (
            id SERIAL PRIMARY KEY,
            section_type VARCHAR(50) NOT NULL,
            title VARCHAR(255),
            subtitle TEXT,
            content TEXT,
            "order" INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # For SQLite, use different syntax
        if database_url.startswith('sqlite'):
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS homepage_section (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section_type VARCHAR(50) NOT NULL,
                title VARCHAR(255),
                subtitle TEXT,
                content TEXT,
                "order" INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        
        conn.execute(text(create_table_sql))
        conn.commit()
        print("✅ HomepageSection table created successfully")

def populate_default_sections():
    """Populate the HomepageSection table with default content"""
    database_url = get_database_url()
    engine = create_engine(database_url)
    
    # Default homepage sections
    default_sections = [
        {
            'section_type': 'how_it_works',
            'title': 'How It Works',
            'subtitle': 'Get started with your AI chatbot in just 5 simple steps',
            'content': json.dumps([
                {
                    'icon': 'fas fa-plus-circle',
                    'title': '1. Create Your Chatbot',
                    'description': 'Start by creating a new chatbot and giving it a name and description.',
                    'color': 'primary'
                },
                {
                    'icon': 'fas fa-upload',
                    'title': '2. Upload Documents',
                    'description': 'Upload PDF, DOCX, or TXT files to train your chatbot with your content.',
                    'color': 'success'
                },
                {
                    'icon': 'fas fa-brain',
                    'title': '3. Train Your Bot',
                    'description': 'Click train to process your documents and make your chatbot intelligent.',
                    'color': 'warning'
                },
                {
                    'icon': 'fas fa-code',
                    'title': '4. Get Embed Code',
                    'description': 'Copy the embed code and paste it into your website to add the chatbot.',
                    'color': 'info'
                },
                {
                    'icon': 'fas fa-rocket',
                    'title': '5. Go Live!',
                    'description': 'Your chatbot is now live and ready to help your website visitors.',
                    'color': 'danger'
                }
            ]),
            'order': 1
        },
        {
            'section_type': 'features',
            'title': 'Powerful Features',
            'subtitle': 'Everything you need to create and manage intelligent chatbots',
            'content': json.dumps([
                {
                    'icon': 'fas fa-check-circle',
                    'title': 'Easy Document Upload',
                    'description': 'Support for PDF, DOCX, and TXT file formats with drag-and-drop interface',
                    'color': 'success'
                },
                {
                    'icon': 'fas fa-check-circle',
                    'title': 'AI-Powered Responses',
                    'description': 'Uses OpenAI GPT technology to understand and respond naturally',
                    'color': 'success'
                },
                {
                    'icon': 'fas fa-check-circle',
                    'title': 'Multiple Chatbots',
                    'description': 'Create unlimited chatbots for different purposes and websites',
                    'color': 'success'
                },
                {
                    'icon': 'fas fa-check-circle',
                    'title': 'Easy Embedding',
                    'description': 'Simple code snippet to embed on any website with customizable styling',
                    'color': 'success'
                }
            ]),
            'order': 2
        },
        {
            'section_type': 'stats',
            'title': 'See It In Action',
            'subtitle': 'Join thousands of users who have already created their chatbots',
            'content': json.dumps([
                {
                    'icon': 'fas fa-robot',
                    'title': 'Chatbots Created',
                    'value': '1000',
                    'color': 'primary'
                },
                {
                    'icon': 'fas fa-file-upload',
                    'title': 'Documents Processed',
                    'value': '5000',
                    'color': 'success'
                },
                {
                    'icon': 'fas fa-comments',
                    'title': 'Conversations',
                    'value': '50000',
                    'color': 'info'
                },
                {
                    'icon': 'fas fa-globe',
                    'title': 'Websites Powered',
                    'value': '100',
                    'color': 'warning'
                }
            ]),
            'order': 3
        },
        {
            'section_type': 'cta',
            'title': 'Ready to Get Started?',
            'subtitle': 'Join thousands of businesses using AI chatbots to improve customer engagement',
            'content': json.dumps({
                'primary_button': {
                    'text': 'Start Building Now',
                    'icon': 'fas fa-rocket',
                    'url': '/register'
                },
                'secondary_button': {
                    'text': 'Contact Us',
                    'icon': 'fas fa-envelope',
                    'url': '/contact'
                }
            }),
            'order': 4
        }
    ]
    
    with engine.connect() as conn:
        # Check if HomepageSection table already has data
        result = conn.execute(text("SELECT COUNT(*) FROM homepage_section"))
        count = result.scalar()
        
        if count == 0:
            # Insert default homepage sections
            for section in default_sections:
                insert_sql = """
                INSERT INTO homepage_section (section_type, title, subtitle, content, "order", is_active, created_at, updated_at)
                VALUES (:section_type, :title, :subtitle, :content, :order, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
                conn.execute(text(insert_sql), section)
            
            conn.commit()
            print(f"✅ Added {len(default_sections)} default homepage sections")
        else:
            print(f"ℹ️ HomepageSection table already contains {count} sections, skipping default population")

def main():
    """Main migration function"""
    print("🚀 Starting Homepage Sections migration...")
    
    try:
        # Create HomepageSection table
        create_homepage_sections_table()
        
        # Populate with default sections
        populate_default_sections()
        
        print("✅ Homepage Sections migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
