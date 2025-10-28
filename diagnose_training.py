#!/usr/bin/env python3
"""
Diagnostic tool for chatbot training issues
"""
import os
import json
from dotenv import load_dotenv
from services.chatbot_trainer import ChatbotTrainer

def diagnose_training_system():
    """Diagnose the training system and provide recommendations"""
    print("CHATBOT TRAINING SYSTEM DIAGNOSTIC")
    print("=" * 50)
    
    # Load environment variables
    load_dotenv()
    
    # Check OpenAI API key
    api_key = os.getenv('OPENAI_API_KEY')
    print(f"OpenAI API Key: {'Configured' if api_key else 'NOT CONFIGURED'}")
    if api_key:
        print(f"   Key length: {len(api_key)} characters")
        print(f"   Key starts with: {api_key[:10]}...")
    else:
        print("   WARNING: This will cause fallback to legacy sentence-based training")
    
    # Initialize trainer
    trainer = ChatbotTrainer()
    print(f"OpenAI Client: {'Available' if trainer.openai_client else 'NOT AVAILABLE'}")
    print(f"AI Libraries: {'Available' if trainer.model else 'NOT AVAILABLE'}")
    
    # Check training data directory
    training_dir = trainer.data_dir
    print(f"Training Data Directory: {training_dir}")
    print(f"   Directory exists: {os.path.exists(training_dir)}")
    
    if os.path.exists(training_dir):
        files = os.listdir(training_dir)
        print(f"   Training files found: {len(files)}")
        for file in files[:5]:  # Show first 5 files
            print(f"     - {file}")
    
    print("\nTRAINING DATA ANALYSIS")
    print("-" * 30)
    
    # Analyze existing training files
    if os.path.exists(training_dir):
        for file in os.listdir(training_dir):
            if file.startswith('chatbot_') and file.endswith('.json'):
                chatbot_id = file.replace('chatbot_', '').replace('.json', '')
                print(f"\nChatbot {chatbot_id}:")
                
                try:
                    training_data = trainer.get_training_data(int(chatbot_id))
                    if training_data:
                        if trainer.is_knowledge_base_format(training_data):
                            print("   Format: Knowledge Base (NEW)")
                            print(f"   Brand: {training_data.get('brand', {}).get('name', 'N/A')}")
                            print(f"   KB Facts: {len(training_data.get('kb_facts', []))}")
                            print(f"   QA Patterns: {len(training_data.get('qa_patterns', []))}")
                            print(f"   Business Info: {'Available' if 'business_info' in training_data else 'Not Available'}")
                        else:
                            print("   Format: Legacy Sentence-based")
                            print(f"   Sentences: {len(training_data.get('sentences', []))}")
                            print(f"   Embeddings: {'Available' if training_data.get('embeddings') else 'Not Available'}")
                            print("   Recommendation: Retrain to use Knowledge Base format")
                    else:
                        print("   No training data found")
                except Exception as e:
                    print(f"   Error reading training data: {e}")
    
    print("\nRECOMMENDATIONS")
    print("-" * 20)
    
    if not api_key:
        print("1. Configure OpenAI API Key:")
        print("   - Create a .env file with: OPENAI_API_KEY=your_key_here")
        print("   - Get API key from: https://platform.openai.com/api-keys")
        print("   - Restart the application after adding the key")
    
    print("\n2. Retrain Existing Chatbots:")
    print("   - Go to each chatbot's details page")
    print("   - Click the 'Train' button")
    print("   - This will convert legacy format to Knowledge Base format")
    
    print("\n3. Knowledge Base Benefits:")
    print("   - Extracts business name, products, services, pricing")
    print("   - Creates structured Q&A patterns")
    print("   - Better search and matching")
    print("   - More accurate responses")
    
    print("\n4. Test Knowledge Base Generation:")
    print("   - Run: python test_kb_generation.py")
    print("   - This will test if the system works correctly")

def test_knowledge_base_with_sample():
    """Test knowledge base generation with sample data"""
    print("\nTESTING KNOWLEDGE BASE GENERATION")
    print("-" * 40)
    
    sample_text = """CompuStore Chatbot Training Document Overview The CompuStore Chatbot is designed to assist website visitors with basic computer hardware questions. It should be friendly, concise, and knowledgeable, while guiding users to products or support when needed.

Core Knowledge Areas Computer Components CPU (Processor): Main brain of the computer. More cores/threads → better multitasking. Higher GHz → faster performance. RAM (Memory): Temporary storage for active tasks. More RAM = smoother multitasking. Common sizes: 8GB (basic), 16GB (standard), 32GB+ (high-end/gaming).

Common Questions & Answers Q: How much RAM do I need? A: 8GB for basic use, 16GB for gaming or professional tasks, 32GB+ for heavy workloads. Q: SSD vs HDD – which should I buy? A: SSDs are faster and better for everyday use. HDDs are cheaper for storing large files."""

    trainer = ChatbotTrainer()
    chatbot_info = {'name': 'CompuStore Assistant', 'description': 'Computer hardware sales and support chatbot'}

    try:
        kb_data = trainer.generate_knowledge_base(sample_text, chatbot_info)
        print("Knowledge Base Generation: SUCCESS")
        print(f"   Brand: {kb_data.get('brand', {}).get('name', 'N/A')}")
        print(f"   KB Facts: {len(kb_data.get('kb_facts', []))}")
        print(f"   QA Patterns: {len(kb_data.get('qa_patterns', []))}")
        print(f"   Business Info: {'Available' if 'business_info' in kb_data else 'Not Available'}")
        
        # Show sample extracted information
        if 'business_info' in kb_data:
            biz_info = kb_data['business_info']
            print(f"   Products: {len(biz_info.get('products', []))}")
            print(f"   Services: {len(biz_info.get('services', []))}")
            print(f"   Plans: {len(biz_info.get('plans', []))}")
        
        return True
    except Exception as e:
        print(f"Knowledge Base Generation: FAILED - {e}")
        return False

if __name__ == '__main__':
    diagnose_training_system()
    test_knowledge_base_with_sample()
