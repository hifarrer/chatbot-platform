import random
from .chatbot_trainer import ChatbotTrainer

class ChatService:
    def __init__(self):
        self.trainer = ChatbotTrainer()
        self.default_responses = [
            "I'm sorry, I don't have information about that topic in my training documents. Could you try asking something else?",
            "I don't have enough information in my training data to answer that question accurately.",
            "Could you please rephrase your question? I want to make sure I understand what you're asking based on my training materials.",
            "I'm not sure about that based on my training documents. Is there anything else I can help you with?",
        ]
    
    def get_response(self, chatbot_id, user_message):
        """
        Generate a response based on the user's message and the chatbot's training data
        """
        print(f" DEBUG: Processing message for chatbot {chatbot_id}: '{user_message}'")
        
        # Store chatbot_id for use in other methods
        self._current_chatbot_id = chatbot_id
        
        # Get chatbot info for custom system prompt
        from app import Chatbot
        chatbot = Chatbot.query.get(chatbot_id)
        if not chatbot:
            return "Chatbot not found."
        
        # Check if training data exists
        training_data = self.trainer.get_training_data(chatbot_id)
        
        # Allow chatbot to work even without documents if it has a custom prompt
        if not training_data and not chatbot.system_prompt:
            print(f" DEBUG: No training data found for chatbot {chatbot_id} and no custom prompt")
            return "I haven't been trained yet. Please upload some documents and train me first!"
        
        if training_data:
            print(f" DEBUG: Found training data with {len(training_data['sentences'])} sentences")
        else:
            print(f" DEBUG: No training data, but chatbot has custom prompt: {chatbot.system_prompt[:50]}...")
        
        # Find similar content from training data
        similar_content = self.trainer.find_similar_content(chatbot_id, user_message, top_k=5)
        
        print(f" DEBUG: Found {len(similar_content)} similar content items")
        for i, item in enumerate(similar_content):
            print(f"   {i+1}. Similarity: {item['similarity']:.3f} - Content: {item['content'][:100]}...")
        
        if not similar_content:
            print(" DEBUG: No similar content found, trying fallback response")
            
            # If no training data but has custom prompt, provide a generic response in character
            if not training_data and chatbot.system_prompt:
                print(" DEBUG: Using custom prompt fallback")
                return self._generate_custom_prompt_response(chatbot.system_prompt, user_message)
            
            # If we have training data but no matches, provide a more helpful response
            if training_data:
                sample_topics = []
                for sentence in training_data['sentences'][:3]:  # Get first 3 sentences as examples
                    if len(sentence.strip()) > 20:
                        # Extract key topics from the sentence
                        clean_sentence = sentence.replace('Q:', '').replace('A:', '').strip()
                        if len(clean_sentence) > 30:
                            sample_topics.append(clean_sentence[:60] + "...")
                
                if sample_topics:
                    topics_text = " | ".join(sample_topics)
                    return f"I have training data but couldn't find a good match for your question. I can help with topics like: {topics_text}. Could you try rephrasing your question?"
            
            return random.choice(self.default_responses)
        
        # Check if we have good enough similarity to use document content
        best_similarity = max(item['similarity'] for item in similar_content) if similar_content else 0
        print(f" DEBUG: Best similarity score: {best_similarity:.3f}")
        
        # If similarity is too low, use system prompt instead of forcing document matches
        if best_similarity < 0.3:
            print(f" DEBUG: Similarity too low ({best_similarity:.3f}), using system prompt response")
            if chatbot.system_prompt:
                return self._generate_custom_prompt_response(chatbot.system_prompt, user_message)
            else:
                return random.choice(self.default_responses)
        
        # Smart Q&A matching - if we find a question, look for the answer
        best_response = self._find_best_response(similar_content, user_message, chatbot)
        
        print(f" DEBUG: Selected response: {best_response[:100]}...")
        return best_response
    
    def _find_best_response(self, similar_content, user_message, chatbot=None):
        """
        Smart logic to find the best response from similar content
        """
        # Look for Q&A pairs (with Q: and A: prefixes)
        for i, item in enumerate(similar_content):
            content = item['content'].strip()
            similarity = item['similarity']
            
            # If we found a question with high similarity, look for the answer
            if content.startswith('Q:') and similarity > 0.3:
                print(f" DEBUG: Found matching Q: question: {content[:50]}...")
                
                # Look for the corresponding answer in the similar content
                for j, answer_item in enumerate(similar_content):
                    answer_content = answer_item['content'].strip()
                    if answer_content.startswith('A:'):
                        print(f" DEBUG: Found corresponding A: answer: {answer_content[:50]}...")
                        return answer_content[2:].strip()  # Remove 'A:' prefix
                
                # If no 'A:' found, look for content that might be an answer
                for j, potential_answer in enumerate(similar_content[1:], 1):  # Skip the question itself
                    answer_content = potential_answer['content'].strip()
                    if not answer_content.startswith('Q:') and len(answer_content) > 20:
                        print(f" DEBUG: Using potential answer after Q: question: {answer_content[:50]}...")
                        return answer_content
        
        # Look for questions without Q: prefix (like "What is Snowflake...")
        for i, item in enumerate(similar_content):
            content = item['content'].strip()
            similarity = item['similarity']
            sentence_index = item.get('index', -1)
            
            # Check if this looks like a question
            if self._is_question_like(content) and similarity > 0.3:
                print(f" DEBUG: Found question-like content at index {sentence_index}: {content[:50]}...")
                
                # First, try to find the answer in the next few sentences
                if sentence_index >= 0:
                    chatbot_id = self._get_chatbot_id_from_context()  # We'll need to pass this
                    for offset in range(1, 4):  # Check next 3 sentences
                        next_sentence = self.trainer.get_sentence_by_index(chatbot_id, sentence_index + offset)
                        if next_sentence and len(next_sentence.strip()) > 20:
                            # Check if this looks like an answer (not another question)
                            if not self._is_question_like(next_sentence):
                                print(f" DEBUG: Found adjacent answer at index {sentence_index + offset}: {next_sentence[:50]}...")
                                return next_sentence.strip()
                
                # If no adjacent answer found, look in similar content
                for j, potential_answer in enumerate(similar_content):
                    answer_content = potential_answer['content'].strip()
                    
                    # Skip if it's also a question
                    if self._is_question_like(answer_content):
                        continue
                    
                    # Look for content that seems like an answer
                    if (len(answer_content) > 30 and 
                        potential_answer['similarity'] > 0.3 and
                        not answer_content.startswith(('What', 'How', 'Why', 'When', 'Where', 'Which'))):
                        print(f" DEBUG: Found answer for question-like content: {answer_content[:50]}...")
                        return answer_content
        
                    # Look for direct answers (starting with 'A:')
        for item in similar_content:
            content = item['content'].strip()
            if content.startswith('A:') and item['similarity'] > 0.2:
                print(f" DEBUG: Found direct A: answer: {content[:50]}...")
                return content[2:].strip()  # Remove 'A:' prefix
        
        # Get the best non-question content
        for item in similar_content:
            content = item['content'].strip()
            similarity = item['similarity']
            
            # Skip question-like content
            if self._is_question_like(content):
                continue
            
            # Return the first good non-question content
            if similarity > 0.15 and len(content) > 20:
                print(f" DEBUG: Using best non-question content: {content[:50]}...")
                return self._format_response(content, similarity)
        
        # If we still don't have a good answer, check if we should use system prompt instead
        best_match = similar_content[0]
        best_content = best_match['content'].strip()
        similarity = best_match['similarity']
        
        # If similarity is still too low and we have a system prompt, use that instead
        if similarity < 0.2 and chatbot and chatbot.system_prompt:
            print(f" DEBUG: Document match too weak ({similarity:.3f}), falling back to system prompt")
            return self._generate_custom_prompt_response(chatbot.system_prompt, user_message)
        
        print(f" DEBUG: Using fallback response formatting")
        return self._format_response(best_content, similarity)
    
    def _is_question_like(self, content):
        """
        Check if content looks like a question
        """
        content_lower = content.lower().strip()
        
        # Check for question words at the beginning
        question_starters = [
            'what', 'how', 'why', 'when', 'where', 'which', 'who', 'whom',
            'can you', 'could you', 'would you', 'do you', 'does', 'did',
            'is', 'are', 'was', 'were', 'will', 'would', 'should', 'could'
        ]
        
        starts_with_question = any(content_lower.startswith(starter) for starter in question_starters)
        ends_with_question_mark = content.endswith('?')
        
        # Also check for Q: prefix
        has_q_prefix = content.startswith('Q:')
        
        return starts_with_question or ends_with_question_mark or has_q_prefix
    
    def _format_response(self, content, similarity):
        """
        Format the response based on similarity and content type
        """
        original_content = content
        
        # Remove prefixes
        if content.startswith('A:'):
            content = content[2:].strip()
        elif content.startswith('Q:'):
            content = content[2:].strip()
        
        # If this is still a question, try to make it more helpful
        if self._is_question_like(content):
            print(f" DEBUG: Still have a question, trying to make it helpful: {content[:50]}...")
            
            # Convert question to a statement about the topic
            if content.lower().startswith('what is'):
                topic = content[8:].strip().rstrip('?')
                response = f"You're asking about {topic}. Based on my training, this relates to the information I have about {topic}."
            elif content.lower().startswith('how'):
                topic = content[4:].strip().rstrip('?')
                response = f"Regarding how {topic}, I have information about this topic in my training data."
            elif content.lower().startswith('why'):
                topic = content[4:].strip().rstrip('?')
                response = f"Concerning why {topic}, this is covered in my training materials."
            else:
                # Generic fallback for questions
                response = f"You're asking about: {content.rstrip('?')}. I have related information about this topic."
            
            # If similarity is very high, be more direct
            if similarity > 0.9:
                response = f"I found information highly relevant to your question about {content.rstrip('?').lower()}. Let me provide what I know about this topic."
            
            return response
        
        # If similarity is very high, return content directly
        if similarity > 0.8:
            print(" DEBUG: High similarity - returning direct content")
            return content
        
        # If similarity is good, create a response based on the content
        elif similarity > 0.3:
            print(" DEBUG: Medium similarity - generating contextual response")
            return self._generate_contextual_response(content)
        
        # If similarity is low, return a default response
        else:
            print(" DEBUG: Low similarity - returning default response")
            return random.choice(self.default_responses)
    
    def _generate_contextual_response(self, content):
        """
        Generate a contextual response based on content from training documents
        """
        # Response templates that emphasize training document priority
        response_templates = [
            f"Based on my training documents: {content}",
            f"According to the information in my training data: {content}",
            f"From my training materials: {content}",
            f"Based on the documents I've been trained on: {content}",
            content,  # Sometimes just return the content directly
        ]
        
        return random.choice(response_templates)
    
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
            "Hello! I'm here to help you with questions based on my training documents. How can I assist you today?",
            "Hi there! I can answer questions from my training materials. What would you like to know?",
            "Hey! I'm here to help with questions about my training data. What questions do you have?",
            "Good day! I can provide information from my training documents. How may I assist you?",
        ]
        return random.choice(responses)
    
    def _get_chatbot_id_from_context(self):
        """
        This is a temporary solution - we need to pass chatbot_id properly
        For now, we'll modify the get_response method to store it
        """
        return getattr(self, '_current_chatbot_id', None)
    
    def _generate_custom_prompt_response(self, system_prompt, user_message):
        """
        Generate a response based on the custom system prompt when no training data is available
        """
        # Simple pattern matching for common questions
        user_lower = user_message.lower()
        
        # Extract role/character from system prompt
        role_phrases = []
        context_info = ""
        
        if "customer support" in system_prompt.lower():
            role_phrases = [
                "I'm here to help you as your customer support assistant.",
                "As a customer support representative, I'm ready to assist you.",
                "I'm your customer support chatbot, how can I help you today?"
            ]
            context_info = "I can help with product questions, troubleshooting, orders, and general support."
        elif "technical" in system_prompt.lower():
            role_phrases = [
                "I'm here to provide technical assistance.",
                "As a technical assistant, I'm ready to help with your questions.",
                "I can help you with technical questions and guidance."
            ]
            context_info = "I can provide technical guidance, troubleshooting steps, and documentation help."
        elif "sales" in system_prompt.lower():
            role_phrases = [
                "I'm here to help with your purchase decisions.",
                "As a sales assistant, I can help you find what you need.",
                "I'm ready to assist with product information and sales."
            ]
            context_info = "I can help with product information, pricing, and purchase decisions."
        elif "platform" in system_prompt.lower() and "chatbot" in system_prompt.lower():
            role_phrases = [
                "I'm the Platform Assistant, here to help you with owlbee.ai.",
                "As your Platform Assistant, I can guide you through creating and managing chatbots.",
                "I'm here to help you make the most of owlbee.ai."
            ]
            context_info = "I can help with creating chatbots, uploading documents, training, embedding, and platform features."
        else:
            # Extract the first sentence of the system prompt as the role
            first_sentence = system_prompt.split('.')[0] if '.' in system_prompt else system_prompt
            role_phrases = [
                f"{first_sentence}. How can I help you?",
                f"I'm here to assist you. {first_sentence}.",
                f"{first_sentence}. What would you like to know?"
            ]
            context_info = "I'm ready to help with questions related to my role."
        
        # Generate contextual responses based on question type
        if any(word in user_lower for word in ['hello', 'hi', 'hey', 'good morning', 'good afternoon']):
            return f"Hello! {random.choice(role_phrases)} {context_info}"
        elif any(word in user_lower for word in ['help', 'support', 'assist', 'can you help']):
            return f"{random.choice(role_phrases)} {context_info} What specific area would you like help with?"
        elif any(word in user_lower for word in ['what can you do', 'what do you do', 'capabilities']):
            return f"{random.choice(role_phrases)} {context_info} Feel free to ask me anything related to my role!"
        elif any(word in user_lower for word in ['what', 'how', 'why', 'when', 'where', 'who']):
            # More intelligent responses based on common question patterns
            if 'what is' in user_lower or 'what are' in user_lower:
                return f"I'd be happy to explain that for you. {random.choice(role_phrases)} Could you provide more specific details about what you'd like to know?"
            elif 'how do' in user_lower or 'how to' in user_lower or 'how can' in user_lower:
                return f"I can help guide you through that process. {random.choice(role_phrases)} Could you tell me more specifically what you're trying to accomplish?"
            elif 'why' in user_lower:
                return f"That's a great question! {random.choice(role_phrases)} Could you provide more context so I can give you a helpful explanation?"
            else:
                return f"I'd be happy to help answer that question. {random.choice(role_phrases)} Could you provide more specific details about what you're looking for?"
        elif any(word in user_lower for word in ['thank', 'thanks']):
            return f"You're welcome! {random.choice(role_phrases)} Is there anything else I can help you with?"
        else:
            return f"{random.choice(role_phrases)} {context_info} Could you tell me more about what you need help with?" 