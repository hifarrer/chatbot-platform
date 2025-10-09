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
            "I'm sorry, I don't have information about that topic in my training documents.",
            "I don't have enough information in my training data to answer that question accurately.",
            "Could you please ask something related to the documents I've been trained on?",
        ]
        
        # Track conversation context for Responses API
        self.conversation_contexts = {}
    
    def get_response(self, chatbot_id, user_message, conversation_id=None):
        """
        Generate a response using OpenAI Responses API with built-in memory
        """
        print(f"🤖 DEBUG: Processing OpenAI Responses API request for chatbot {chatbot_id}: '{user_message}'")
        
        # Get chatbot info for custom system prompt
        from app import Chatbot
        chatbot = Chatbot.query.get(chatbot_id)
        if not chatbot:
            return "Chatbot not found."
        
        # Get relevant context from training data
        context = self._get_relevant_context(chatbot_id, user_message)
        
        # Check if we need web search as fallback
        needs_web_search = self._should_use_web_search(context, user_message)
        
        # Allow chatbot to work even without documents if it has a custom prompt
        if not context and not chatbot.system_prompt:
            print("❌ DEBUG: No training data found and no custom prompt")
            return "I haven't been trained yet. Please upload some documents and train me first!"
        
        if context:
            print(f"📄 DEBUG: Using context from {len(context)} relevant passages")
        else:
            print("📄 DEBUG: No document context, using custom prompt only")
        
        # Create the system prompt for OpenAI using chatbot's custom system prompt
        system_prompt = self._create_system_prompt_for_responses(context, chatbot.system_prompt)
        
        try:
            # Determine if we should use web search model
            if needs_web_search:
                selected_model = 'gpt-4o-search-preview'
                print(f"🌐 DEBUG: Using OpenAI web search model: {selected_model}")
            else:
                # Get the selected model from database settings
                from app import Settings
                setting = Settings.query.filter_by(key='openai_model').first()
                selected_model = setting.value if setting else 'gpt-3.5-turbo'
                print(f"🤖 DEBUG: Using OpenAI model: {selected_model}")
            
            # Prepare the input for Responses API
            input_text = f"{system_prompt}\n\nUser: {user_message}"
            
            # Check if this is a continuation of a conversation
            previous_response_id = None
            if conversation_id and conversation_id in self.conversation_contexts:
                previous_response_id = self.conversation_contexts[conversation_id]
                print(f"🔄 DEBUG: Continuing conversation with previous_response_id: {previous_response_id}")
            else:
                print(f"🆕 DEBUG: Starting new conversation")
            
            # Call OpenAI Responses API with web search if needed
            if needs_web_search:
                # Use chat completions API for web search model
                response = self.client.chat.completions.create(
                    model=selected_model,
                    web_search_options={},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ]
                )
                answer = response.choices[0].message.content.strip()
            elif previous_response_id:
                response = self.client.responses.create(
                    model=selected_model,
                    previous_response_id=previous_response_id,
                    input=input_text
                )
                answer = response.output_text.strip()
            else:
                response = self.client.responses.create(
                    model=selected_model,
                    input=input_text
                )
                answer = response.output_text.strip()
            
            # Store the response ID for future conversation continuity (only for Responses API)
            if conversation_id and not needs_web_search:
                self.conversation_contexts[conversation_id] = response.id
                print(f"💾 DEBUG: Stored response_id {response.id} for conversation {conversation_id}")
            
            print(f"✅ DEBUG: OpenAI response generated: {answer[:100]}...")
            return answer
            
        except Exception as e:
            print(f"❌ DEBUG: OpenAI Responses API error: {e}")
            
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
    
    def _should_use_web_search(self, context_passages, user_message):
        """
        Determine if web search should be used as fallback
        """
        # Get similarity threshold from settings
        try:
            from app import Settings
            setting = Settings.query.filter_by(key='web_search_min_similarity').first()
            min_similarity = float(setting.value) if setting else 0.3
        except:
            min_similarity = 0.3
        
        # If we have good context from training documents, don't search
        if context_passages:
            # Check if any context has high relevance
            for passage in context_passages:
                if "[Relevance:" in passage:
                    try:
                        relevance = float(passage.split("[Relevance: ")[1].split("]")[0])
                        if relevance > min_similarity:  # Good match from training docs
                            return False
                    except:
                        pass
        
        # Check for keywords that suggest external information is needed
        external_keywords = [
            'current', 'latest', 'recent', 'news', 'today', 'now',
            'latest news', 'recent events', 'current events', 'today\'s',
            'what\'s happening', 'breaking news', 'live', 'real-time'
        ]
        
        message_lower = user_message.lower()
        for keyword in external_keywords:
            if keyword in message_lower:
                print(f"🔍 DEBUG: External keyword '{keyword}' detected, web search recommended")
                return True
        
        # If no good training context and no external keywords, still consider web search
        # but with lower priority
        return len(context_passages) == 0
    
    def _create_system_prompt_for_responses(self, context_passages, custom_prompt=None):
        """
        Create a system prompt for OpenAI Responses API with the relevant context and custom prompt
        This is optimized for the Responses API format
        """
        # Use custom prompt if provided, otherwise use default
        base_prompt = custom_prompt or "You are a helpful AI assistant trained on specific documents. Your job is to answer questions based on the information provided in the context below."
        
        # Get training prompt from database
        from app import get_setting
        training_prompt_template = get_setting('training_prompt', '')
        
        if context_passages:
            context_text = "\n\n".join(context_passages)
            
            # Use database prompt if available, otherwise use default
            if training_prompt_template:
                # Replace placeholders in the template
                system_prompt = training_prompt_template.format(
                    base_prompt=base_prompt,
                    context_text=context_text
                )
            else:
                # Fallback to hardcoded prompt
                system_prompt = f"""{base_prompt}

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
        else:
            # No documents, use database prompt or fallback
            if training_prompt_template:
                # Use database prompt template without context
                system_prompt = training_prompt_template.format(
                    base_prompt=base_prompt,
                    context_text=""
                )
            else:
                # Fallback to hardcoded prompt
                system_prompt = f"""{base_prompt}

INSTRUCTIONS:
1. Follow your role as defined above
2. Be conversational and helpful in your tone
3. Use your general knowledge to answer questions while staying in character
4. Keep your answers concise but complete
5. If you don't know something specific to your role, say so politely
6. IMPORTANT: After providing your answer, always end with a follow-up question to encourage continued conversation. Use phrases like:
   - "May I help you with anything else?"
   - "Have I answered all of your questions?"
   - "Is there anything else you'd like to know about this topic?"
   - "Would you like me to explain anything else?"
   - "Do you have any other questions?"

TRAINING DOCUMENT PRIORITY:
- When training documents are available, ALWAYS prioritize information from those documents over general knowledge
- If training documents contain information that conflicts with general knowledge, always use the training document information
- Only use general knowledge when training documents don't cover the specific topic

Remember: Stay in character as defined in your role."""

        return system_prompt
    
    def clear_conversation_context(self, conversation_id):
        """
        Clear conversation context for a specific conversation
        """
        if conversation_id in self.conversation_contexts:
            del self.conversation_contexts[conversation_id]
            print(f"🗑️ DEBUG: Cleared conversation context for {conversation_id}")
    
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