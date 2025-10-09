#!/usr/bin/env python3
"""
Migration script to add the default training prompt to the database.
Run this script to initialize the training prompt setting.
"""

import os
import sys
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, Settings

def migrate_add_training_prompt():
    """Add the default training prompt to the database"""
    app = create_app()
    
    with app.app_context():
        # Check if training prompt already exists
        existing_prompt = Settings.query.filter_by(key='training_prompt').first()
        
        if existing_prompt:
            print("✅ Training prompt already exists in database")
            print(f"Current value: {existing_prompt.value[:100]}...")
            return
        
        # Default training prompt
        default_training_prompt = """{base_prompt}

TRAINING DOCUMENTS CONTEXT:
{context_text}

CRITICAL INSTRUCTIONS - TRAINING DOCUMENT PRIORITY:
1. ALWAYS answer questions based on the training documents provided above FIRST
2. ONLY use your general knowledge or web search if the training documents don't contain relevant information
3. When training documents contain relevant information, base your response entirely on that content
4. If training documents have conflicting information with general knowledge, prioritize the training documents
5. Never contradict information from the training documents with external knowledge
6. If you must use general knowledge or web search, clearly state that the training documents don't cover that specific aspect

RESPONSE GUIDELINES:
1. Follow your role as defined above
2. Use the information from the training documents when relevant
3. If the context doesn't contain enough information to answer the question, you may use your general knowledge while staying in character
4. Be conversational and helpful in your tone
5. Keep your answers concise but complete
6. If you see Q&A pairs in the context, use them to inform your responses
7. If multiple pieces of context are relevant, synthesize them into a coherent answer
8. IMPORTANT: After providing your answer, always end with a follow-up question to encourage continued conversation. Use phrases like:
   - "May I help you with anything else?"
   - "Have I answered all of your questions?"
   - "Is there anything else you'd like to know about this topic?"
   - "Would you like me to explain anything else?"
   - "Do you have any other questions?"

Remember: Stay in character as defined in your role, and ALWAYS prioritize information from the training documents when available."""
        
        # Create new training prompt setting
        training_prompt_setting = Settings(
            key='training_prompt',
            value=default_training_prompt,
            updated_at=datetime.utcnow()
        )
        
        try:
            db.session.add(training_prompt_setting)
            db.session.commit()
            print("✅ Successfully added training prompt to database")
            print("📝 You can now manage the training prompt from the admin dashboard")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error adding training prompt: {e}")
            return False
    
    return True

if __name__ == '__main__':
    print("🚀 Starting training prompt migration...")
    success = migrate_add_training_prompt()
    
    if success:
        print("✅ Migration completed successfully!")
    else:
        print("❌ Migration failed!")
        sys.exit(1)
