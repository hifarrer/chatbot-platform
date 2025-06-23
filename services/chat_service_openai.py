from openai import OpenAI
import random
import os
from .chatbot_trainer import ChatbotTrainer

class ChatServiceOpenAI:
    def __init__(self):
        # Get OpenAI API key from environment variable
        self.api_key = os.getenv('OPENAI_API_KEY')
        
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        # Initialize OpenAI client with the new v1.0+ API
        self.client = OpenAI(api_key=self.api_key)
        
        self.trainer = ChatbotTrainer()
        self.default_responses = [
            "I'm sorry, I don't have information about that topic in my training data.",
            "I don't have enough information to answer that question accurately.",
            "Could you please ask something related to the documents I've been trained on?",
        ]
    
    def get_response(self, chatbot_id, user_message):
        """
        Generate a response using OpenAI GPT with context from training data
        """
        print(f"🤖 DEBUG: Processing OpenAI request for chatbot {chatbot_id}: '{user_message}'")
        
        # Get relevant context from training data
        context = self._get_relevant_context(chatbot_id, user_message)
        
        if not context:
            print("❌ DEBUG: No training data found")
            return "I haven't been trained yet. Please upload some documents and train me first!"
        
        print(f"📄 DEBUG: Using context from {len(context)} relevant passages")
        
        # Create the prompt for OpenAI
        system_prompt = self._create_system_prompt(context)
        
        try:
            # Call OpenAI API using the new v1.0+ syntax
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=500,
                temperature=0.7,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0
            )
            
            answer = response.choices[0].message.content.strip()
            print(f"✅ DEBUG: OpenAI response generated: {answer[:100]}...")
            return answer
            
        except Exception as e:
            print(f"❌ DEBUG: OpenAI API error: {e}")
            
            # Fallback to local similarity matching if OpenAI fails
            similar_content = self.trainer.find_similar_content(chatbot_id, user_message, top_k=1)
            if similar_content and similar_content[0]['similarity'] > 0.3:
                return similar_content[0]['content']
            else:
                return random.choice(self.default_responses)
    
    def _get_relevant_context(self, chatbot_id, user_message, max_context_length=2000):
        """
        Get relevant context from training data using similarity search
        """
        # Find similar content
        similar_content = self.trainer.find_similar_content(chatbot_id, user_message, top_k=5)
        
        print(f"🔍 DEBUG: Found {len(similar_content)} similar content items")
        for i, item in enumerate(similar_content):
            print(f"   {i+1}. Similarity: {item['similarity']:.3f} - Content: {item['content'][:50]}...")
        
        if not similar_content:
            print("❌ DEBUG: No similar content found by trainer")
            return None
        
        # Build context from most relevant passages
        context_passages = []
        total_length = 0
        
        for item in similar_content:
            content = item['content'].strip()
            similarity = item['similarity']
            
            # Only include reasonably relevant content
            if similarity > 0.1:
                # Add some context about relevance
                passage = f"[Relevance: {similarity:.2f}] {content}"
                
                if total_length + len(passage) < max_context_length:
                    context_passages.append(passage)
                    total_length += len(passage)
                else:
                    break
        
        # If no content met the threshold, include the best matches anyway
        if not context_passages and similar_content:
            print("⚠️ DEBUG: No content met similarity threshold, using best matches anyway")
            for item in similar_content[:3]:  # Take top 3 regardless of score
                content = item['content'].strip()
                similarity = item['similarity']
                passage = f"[Relevance: {similarity:.2f}] {content}"
                
                if total_length + len(passage) < max_context_length:
                    context_passages.append(passage)
                    total_length += len(passage)
                else:
                    break
        
        print(f"📄 DEBUG: Final context has {len(context_passages)} passages, total length: {total_length}")
        for i, passage in enumerate(context_passages):
            print(f"   Context {i+1}: {passage[:100]}...")
        
        return context_passages
    
    def _create_system_prompt(self, context_passages):
        """
        Create a system prompt for OpenAI with the relevant context
        """
        context_text = "\n\n".join(context_passages)
        
        system_prompt = f"""You are a helpful AI assistant trained on specific documents. Your job is to answer questions based ONLY on the information provided in the context below.

CONTEXT FROM TRAINING DOCUMENTS:
{context_text}

INSTRUCTIONS:
1. Answer questions based ONLY on the information provided in the context above
2. If the context doesn't contain enough information to answer the question, say so politely
3. Be conversational and helpful in your tone
4. Keep your answers concise but complete
5. If you see Q&A pairs in the context, use them to inform your responses
6. Don't make up information that's not in the context
7. If multiple pieces of context are relevant, synthesize them into a coherent answer

Remember: You can only use information from the context provided above. Do not use your general knowledge beyond what's in the training context."""

        return system_prompt
    
    def is_greeting(self, message):
        """
        Check if the message is a greeting
        """
        greetings = ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening']
        return any(greeting in message.lower() for greeting in greetings)
    
    def get_greeting_response(self):
        """
        Get a greeting response
        """
        responses = [
            "Hello! I'm here to help you with questions about the documents I've been trained on. What would you like to know?",
            "Hi there! I can answer questions based on my training documents. How can I assist you?",
            "Hey! I'm ready to help with any questions about my training materials. What can I help you with?",
            "Good day! I'm here to provide information from my training documents. What would you like to learn about?",
        ]
        return random.choice(responses) 