import random
from .chatbot_trainer import ChatbotTrainer

class ChatService:
    def __init__(self):
        self.trainer = ChatbotTrainer()
        self.default_responses = [
            "I'm sorry, I don't have information about that topic. Could you try asking something else?",
            "I don't have enough information to answer that question accurately.",
            "Could you please rephrase your question? I want to make sure I understand what you're asking.",
            "I'm not sure about that. Is there anything else I can help you with?",
        ]
    
    def get_response(self, chatbot_id, user_message):
        """
        Generate a response based on the user's message and the chatbot's training data
        """
        print(f"🔍 DEBUG: Processing message for chatbot {chatbot_id}: '{user_message}'")
        
        # Store chatbot_id for use in other methods
        self._current_chatbot_id = chatbot_id
        
        # Check if training data exists
        training_data = self.trainer.get_training_data(chatbot_id)
        if not training_data:
            print(f"❌ DEBUG: No training data found for chatbot {chatbot_id}")
            return "I haven't been trained yet. Please upload some documents and train me first!"
        
        print(f"✅ DEBUG: Found training data with {len(training_data['sentences'])} sentences")
        
        # Find similar content from training data
        similar_content = self.trainer.find_similar_content(chatbot_id, user_message, top_k=5)
        
        print(f"🔍 DEBUG: Found {len(similar_content)} similar content items")
        for i, item in enumerate(similar_content):
            print(f"   {i+1}. Similarity: {item['similarity']:.3f} - Content: {item['content'][:100]}...")
        
        if not similar_content:
            print("❌ DEBUG: No similar content found, trying fallback response")
            # If we have training data but no matches, provide a more helpful response
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
            else:
                return random.choice(self.default_responses)
        
        # Smart Q&A matching - if we find a question, look for the answer
        best_response = self._find_best_response(similar_content, user_message)
        
        print(f"🎯 DEBUG: Selected response: {best_response[:100]}...")
        return best_response
    
    def _find_best_response(self, similar_content, user_message):
        """
        Smart logic to find the best response from similar content
        """
        # Look for Q&A pairs (with Q: and A: prefixes)
        for i, item in enumerate(similar_content):
            content = item['content'].strip()
            similarity = item['similarity']
            
            # If we found a question with high similarity, look for the answer
            if content.startswith('Q:') and similarity > 0.3:
                print(f"🔍 DEBUG: Found matching Q: question: {content[:50]}...")
                
                # Look for the corresponding answer in the similar content
                for j, answer_item in enumerate(similar_content):
                    answer_content = answer_item['content'].strip()
                    if answer_content.startswith('A:'):
                        print(f"✅ DEBUG: Found corresponding A: answer: {answer_content[:50]}...")
                        return answer_content[2:].strip()  # Remove 'A:' prefix
                
                # If no 'A:' found, look for content that might be an answer
                for j, potential_answer in enumerate(similar_content[1:], 1):  # Skip the question itself
                    answer_content = potential_answer['content'].strip()
                    if not answer_content.startswith('Q:') and len(answer_content) > 20:
                        print(f"✅ DEBUG: Using potential answer after Q: question: {answer_content[:50]}...")
                        return answer_content
        
        # Look for questions without Q: prefix (like "What is Snowflake...")
        for i, item in enumerate(similar_content):
            content = item['content'].strip()
            similarity = item['similarity']
            sentence_index = item.get('index', -1)
            
            # Check if this looks like a question
            if self._is_question_like(content) and similarity > 0.3:
                print(f"🔍 DEBUG: Found question-like content at index {sentence_index}: {content[:50]}...")
                
                # First, try to find the answer in the next few sentences
                if sentence_index >= 0:
                    chatbot_id = self._get_chatbot_id_from_context()  # We'll need to pass this
                    for offset in range(1, 4):  # Check next 3 sentences
                        next_sentence = self.trainer.get_sentence_by_index(chatbot_id, sentence_index + offset)
                        if next_sentence and len(next_sentence.strip()) > 20:
                            # Check if this looks like an answer (not another question)
                            if not self._is_question_like(next_sentence):
                                print(f"✅ DEBUG: Found adjacent answer at index {sentence_index + offset}: {next_sentence[:50]}...")
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
                        print(f"✅ DEBUG: Found answer for question-like content: {answer_content[:50]}...")
                        return answer_content
        
                    # Look for direct answers (starting with 'A:')
        for item in similar_content:
            content = item['content'].strip()
            if content.startswith('A:') and item['similarity'] > 0.2:
                print(f"✅ DEBUG: Found direct A: answer: {content[:50]}...")
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
                print(f"✅ DEBUG: Using best non-question content: {content[:50]}...")
                return self._format_response(content, similarity)
        
        # If we still don't have a good answer, use the best match but format it better
        best_match = similar_content[0]
        best_content = best_match['content'].strip()
        similarity = best_match['similarity']
        
        print(f"⚠️ DEBUG: Using fallback response formatting")
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
            print(f"⚠️ DEBUG: Still have a question, trying to make it helpful: {content[:50]}...")
            
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
            print("✅ DEBUG: High similarity - returning direct content")
            return content
        
        # If similarity is good, create a response based on the content
        elif similarity > 0.3:
            print("✅ DEBUG: Medium similarity - generating contextual response")
            return self._generate_contextual_response(content)
        
        # If similarity is low, return a default response
        else:
            print("❌ DEBUG: Low similarity - returning default response")
            return random.choice(self.default_responses)
    
    def _generate_contextual_response(self, content):
        """
        Generate a contextual response based on content
        """
        # Simple response templates
        response_templates = [
            f"Based on the information I have: {content}",
            f"Here's what I found: {content}",
            f"According to my training data: {content}",
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
            "Hello! How can I help you today?",
            "Hi there! What would you like to know?",
            "Hey! I'm here to help. What questions do you have?",
            "Good day! How may I assist you?",
        ]
        return random.choice(responses)
    
    def _get_chatbot_id_from_context(self):
        """
        This is a temporary solution - we need to pass chatbot_id properly
        For now, we'll modify the get_response method to store it
        """
        return getattr(self, '_current_chatbot_id', None) 