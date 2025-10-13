from openai import OpenAI
import random
import os
import re
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
        print(f" DEBUG: Processing OpenAI Responses API request for chatbot {chatbot_id}: '{user_message}'")
        
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
            print(" DEBUG: No training data found and no custom prompt")
            return "I haven't been trained yet. Please upload some documents and train me first!"
        
        if context:
            print(f" DEBUG: Using context from {len(context)} relevant passages")
        else:
            print(" DEBUG: No document context, using custom prompt only")
        
        # Create the system prompt for OpenAI using chatbot's custom system prompt
        print(f" DEBUG: Creating system prompt with {len(context) if context else 0} context passages")
        system_prompt = self._create_system_prompt_for_responses(context, chatbot.system_prompt)
        print(f" DEBUG: System prompt length: {len(system_prompt)} characters")
        print(f" DEBUG: System prompt preview: {system_prompt[:200]}...")
        
        # FULL PROMPT LOGGING - Show the complete prompt being sent to OpenAI
        print("\n" + "="*80)
        print("FULL SYSTEM PROMPT BEING SENT TO OPENAI:")
        print("="*80)
        print(system_prompt)
        print("="*80)
        print("END OF FULL SYSTEM PROMPT")
        print("="*80 + "\n")
        
        try:
            # Determine if we should use web search model
            if needs_web_search:
                selected_model = 'gpt-4o-search-preview'
                print(f" DEBUG: Using OpenAI web search model: {selected_model}")
            else:
                # Get the selected model from database settings
                try:
                    from app import Settings
                    setting = Settings.query.filter_by(key='openai_model').first()
                    selected_model = setting.value if setting else 'gpt-3.5-turbo'
                except Exception as e:
                    print(f" DEBUG: Error accessing database for OpenAI model: {e}")
                    selected_model = 'gpt-3.5-turbo'
                print(f" DEBUG: Using OpenAI model: {selected_model}")
            
            # Prepare the input for Responses API
            input_text = f"{system_prompt}\n\nUser: {user_message}"
            
            # FULL INPUT LOGGING - Show the complete input being sent to OpenAI
            print("\n" + "="*80)
            print("FULL INPUT TEXT BEING SENT TO OPENAI:")
            print("="*80)
            print(input_text)
            print("="*80)
            print("END OF FULL INPUT TEXT")
            print("="*80 + "\n")
            
            # Check if this is a continuation of a conversation
            previous_response_id = None
            if conversation_id and conversation_id in self.conversation_contexts:
                previous_response_id = self.conversation_contexts[conversation_id]
                print(f" DEBUG: Continuing conversation with previous_response_id: {previous_response_id}")
            else:
                print(f" DEBUG: Starting new conversation")
            
            # Call OpenAI Responses API with web search if needed
            if needs_web_search:
                # Use chat completions API for web search model
                try:
                    response = self.client.chat.completions.create(
                        model=selected_model,
                        web_search_options={},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ]
                    )
                    answer = response.choices[0].message.content.strip()
                    print(f" DEBUG: Web search API call successful")
                except Exception as e:
                    print(f" DEBUG: Web search API call failed: {e}")
                    raise e
            elif previous_response_id:
                try:
                    response = self.client.responses.create(
                        model=selected_model,
                        previous_response_id=previous_response_id,
                        input=input_text
                    )
                    answer = response.output_text.strip()
                    print(f" DEBUG: Responses API call with previous_response_id successful")
                except Exception as e:
                    print(f" DEBUG: Responses API call with previous_response_id failed: {e}")
                    raise e
            else:
                try:
                    response = self.client.responses.create(
                        model=selected_model,
                        input=input_text
                    )
                    answer = response.output_text.strip()
                    print(f" DEBUG: Responses API call successful")
                except Exception as e:
                    print(f" DEBUG: Responses API call failed: {e}")
                    raise e
            
            # Store the response ID for future conversation continuity (only for Responses API)
            if conversation_id and not needs_web_search:
                self.conversation_contexts[conversation_id] = response.id
                print(f" DEBUG: Stored response_id {response.id} for conversation {conversation_id}")
            
            print(f" DEBUG: OpenAI response generated: {answer[:100]}...")
            
            # Clean up unwanted training data references
            print(f" DEBUG: Original answer: {answer[:100]}...")
            try:
                cleaned_answer = self._clean_training_references(answer)
                print(f" DEBUG: Cleaned response: {cleaned_answer[:100]}...")
                
                # Format the response for better readability
                formatted_answer = self._format_response_text(cleaned_answer)
                print(f" DEBUG: Formatted response: {formatted_answer[:100]}...")
                
                # Show if JSON conversion was triggered
                if "Here are the available plans:" in formatted_answer:
                    print(" DEBUG: JSON table conversion was triggered!")
                else:
                    print(" DEBUG: JSON table conversion was NOT triggered")
                    
            except Exception as e:
                print(f" DEBUG: Error in response processing: {e}")
                # Fallback to original answer
                formatted_answer = answer
            
            return formatted_answer
            
        except Exception as e:
            print(f" DEBUG: OpenAI Responses API error: {e}")
            print(f" DEBUG: Error type: {type(e).__name__}")
            print(f" DEBUG: Error details: {str(e)}")
            
            # Fallback to local similarity matching if OpenAI fails
            similar_content = self.trainer.find_similar_content(chatbot_id, user_message, top_k=1)
            if similar_content and similar_content[0]['similarity'] > 0.3:
                fallback_response = similar_content[0]['content']
                # Clean up training references from fallback response too
                cleaned_response = self._clean_training_references(fallback_response)
                # Format the response for better readability
                return self._format_response_text(cleaned_response)
            else:
                return random.choice(self.default_responses)
    
    def _get_relevant_context(self, chatbot_id, user_message, max_context_length=2000):
        """
        Get relevant context from training data.
        Uses knowledge base format if available, otherwise falls back to similarity search.
        """
        print(f" DEBUG: Getting relevant context for chatbot {chatbot_id}")
        print(f" DEBUG: User message: '{user_message}'")
        
        # First check if we have knowledge base format
        training_data = self.trainer.get_training_data(chatbot_id)
        
        if training_data and self.trainer.is_knowledge_base_format(training_data):
            print(" DEBUG: Using knowledge base format for context")
            return self._get_context_from_knowledge_base(chatbot_id, user_message, max_context_length)
        
        # Fall back to legacy similarity search
        print(" DEBUG: Using legacy similarity search for context")
        
        # Find similar content
        similar_content = self.trainer.find_similar_content(chatbot_id, user_message, top_k=5)
        
        print(f" DEBUG: Found {len(similar_content)} similar content items")
        for i, item in enumerate(similar_content):
            print(f"   {i+1}. Similarity: {item['similarity']:.3f} - Content: {item['content'][:50]}...")
        
        if not similar_content:
            print(" DEBUG: No similar content found by trainer")
            return None
        
        # Build context from most relevant passages with smart prioritization
        context_passages = []
        total_length = 0
        
        # Sort by similarity and content quality
        sorted_content = sorted(similar_content, key=lambda x: (x['similarity'], len(x['content'])), reverse=True)
        
        for item in sorted_content:
            content = item['content'].strip()
            similarity = item['similarity']
            
            # Only include reasonably relevant content
            if similarity > 0.1:
                # Prioritize detailed content over generic responses
                is_detailed = len(content) > 100 and any(keyword in content.lower() for keyword in ['plan', 'price', 'feature', 'detail', 'information'])
                is_generic = any(phrase in content.lower() for phrase in ['visit the', 'check the', 'go to', 'see the'])
                
                # Skip generic responses if we have detailed content
                if is_generic and any(len(p.split('] ', 1)[1] if '] ' in p else p) > 100 for p in context_passages):
                    print(f" DEBUG: Skipping generic response in favor of detailed content")
                    continue
                
                # Add some context about relevance
                passage = f"[Relevance: {similarity:.2f}] {content}"
                
                if total_length + len(passage) < max_context_length:
                    context_passages.append(passage)
                    total_length += len(passage)
                    print(f" DEBUG: Added context passage (length: {len(passage)})")
                else:
                    break
        
        # If no content met the threshold, include the best matches anyway
        if not context_passages and similar_content:
            print(" DEBUG: No content met similarity threshold, using best matches anyway")
            for item in similar_content[:3]:  # Take top 3 regardless of score
                content = item['content'].strip()
                similarity = item['similarity']
                passage = f"[Relevance: {similarity:.2f}] {content}"
                
                if total_length + len(passage) < max_context_length:
                    context_passages.append(passage)
                    total_length += len(passage)
                else:
                    break
        
        print(f" DEBUG: Final context has {len(context_passages)} passages, total length: {total_length}")
        for i, passage in enumerate(context_passages):
            print(f"   Context {i+1}: {passage[:100]}...")
        
        return context_passages
    
    def _get_context_from_knowledge_base(self, chatbot_id, user_message, max_context_length=2000):
        """
        Get relevant context from knowledge base format
        """
        print(f" DEBUG: Querying knowledge base for context")
        
        # Query the knowledge base
        kb_results = self.trainer.query_knowledge_base(chatbot_id, user_message, top_k=5)
        
        if not kb_results or not kb_results.get('matches'):
            print(" DEBUG: No matches found in knowledge base")
            return None
        
        matches = kb_results['matches']
        brand = kb_results.get('brand', {})
        
        print(f" DEBUG: Found {len(matches)} matches in knowledge base")
        
        # Build context from matches
        context_passages = []
        total_length = 0
        
        for match in matches:
            match_type = match['type']
            score = match['score']
            
            # Build passage based on match type
            if match_type == 'qa_pattern':
                # QA Pattern match - use the response directly
                intent_id = match['intent_id']
                response = match.get('response_inline', '')
                
                # If there's a reference to a KB fact, include that too
                if match.get('response_ref'):
                    ref_id = match['response_ref']
                    # Find the referenced fact
                    training_data = self.trainer.get_training_data(chatbot_id)
                    for fact in training_data.get('kb_facts', []):
                        if fact['id'] == ref_id:
                            response = f"{response}\n\nDetails: {fact['answer_long']}"
                            break
                
                passage = f"[Relevance: {score:.2f}] [Intent: {intent_id}]\n{response}"
                
            elif match_type == 'kb_fact':
                # KB Fact match - use the detailed answer
                fact_id = match['fact_id']
                title = match['title']
                answer_long = match['answer_long']
                
                passage = f"[Relevance: {score:.2f}] [Topic: {title}]\n{answer_long}"
            
            else:
                continue
            
            # Add passage if it fits in context length
            if total_length + len(passage) < max_context_length:
                context_passages.append(passage)
                total_length += len(passage)
                print(f" DEBUG: Added knowledge base passage (length: {len(passage)})")
            else:
                break
        
        # If no passages fit, include at least the top match (truncated if necessary)
        if not context_passages and matches:
            top_match = matches[0]
            if top_match['type'] == 'qa_pattern':
                passage = f"[Relevance: {top_match['score']:.2f}] {top_match.get('response_inline', '')}"
            else:
                passage = f"[Relevance: {top_match['score']:.2f}] {top_match.get('answer_long', top_match.get('answer_short', ''))}"
            
            if len(passage) > max_context_length:
                passage = passage[:max_context_length] + "..."
            
            context_passages.append(passage)
            print(f" DEBUG: Added truncated top match")
        
        print(f" DEBUG: Final knowledge base context has {len(context_passages)} passages, total length: {total_length}")
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
                print(f" DEBUG: External keyword '{keyword}' detected, web search recommended")
                return True
        
        # If no good training context and no external keywords, still consider web search
        # but with lower priority
        return len(context_passages) == 0
    
    def _create_system_prompt_for_responses(self, context_passages, custom_prompt=None):
        """
        Create a system prompt for OpenAI Responses API with the relevant context and custom prompt
        This uses the admin training prompt template with the chatbot's custom prompt and training context
        """
        # Get the admin training prompt template from database
        try:
            from app import Settings
            setting = Settings.query.filter_by(key='training_prompt').first()
            training_prompt_template = setting.value if setting else ''
            print(f" DEBUG: Successfully retrieved training prompt from database: {len(training_prompt_template)} characters")
        except Exception as e:
            print(f" DEBUG: Error accessing database for training prompt: {e}")
            training_prompt_template = ''
        
        # LOGGING: Show the training prompt template from database
        print("\n" + "="*80)
        print("ADMIN TRAINING PROMPT TEMPLATE FROM DATABASE:")
        print("="*80)
        print(training_prompt_template)
        print("="*80)
        print("END OF ADMIN TRAINING PROMPT TEMPLATE")
        print("="*80 + "\n")
        
        if not training_prompt_template:
            print(" DEBUG: No training prompt template found in database settings")
            # Fallback to just the custom prompt if no template
            return custom_prompt or "You are a helpful AI assistant."
        
        # Use the chatbot's custom prompt as the base_prompt placeholder
        base_prompt = custom_prompt or "You are a helpful AI assistant."
        
        # Prepare context text from training documents
        if context_passages:
            context_text = "\n\n".join(context_passages)
        else:
            context_text = ""
        
        print(f" DEBUG: Using admin training prompt template")
        print(f" DEBUG: Base prompt (chatbot's custom prompt): {base_prompt[:100]}...")
        print(f" DEBUG: Context text length: {len(context_text)} characters")
        
        # LOGGING: Show the base prompt and context being used
        print("\n" + "="*80)
        print("BASE PROMPT (CHATBOT'S CUSTOM PROMPT):")
        print("="*80)
        print(base_prompt)
        print("="*80)
        print("END OF BASE PROMPT")
        print("="*80 + "\n")
        
        print("\n" + "="*80)
        print("CONTEXT TEXT (TRAINING DOCUMENTS):")
        print("="*80)
        print(context_text)
        print("="*80)
        print("END OF CONTEXT TEXT")
        print("="*80 + "\n")
        
        # Use the admin training prompt template with placeholders filled
        try:
            system_prompt = training_prompt_template.format(
                base_prompt=base_prompt,
                context_text=context_text
            )
            print(f" DEBUG: Successfully formatted system prompt with placeholders")
        except Exception as e:
            print(f" DEBUG: Error formatting system prompt: {e}")
            print(f" DEBUG: Template: {training_prompt_template[:200]}...")
            print(f" DEBUG: Base prompt: {base_prompt[:100]}...")
            print(f" DEBUG: Context text length: {len(context_text)}")
            # Fallback to simple concatenation
            system_prompt = f"{base_prompt}\n\nTRAINING DOCUMENTS CONTEXT:\n{context_text}"
        
        # LOGGING: Show the final formatted system prompt
        print("\n" + "="*80)
        print("FINAL FORMATTED SYSTEM PROMPT (AFTER PLACEHOLDER REPLACEMENT):")
        print("="*80)
        print(system_prompt)
        print("="*80)
        print("END OF FINAL FORMATTED SYSTEM PROMPT")
        print("="*80 + "\n")

        return system_prompt
    
    def _clean_training_references(self, text):
        """
        Remove unwanted training data references from AI responses
        """
        if not text:
            return text
        
        # List of phrases to remove (case-insensitive)
        unwanted_phrases = [
            "According to the information in my training data",
            "Based on the documents I've been trained on",
            "Based on my training documents",
            "Based on the documents I've been trained on",
            "According to my training data",
            "Based on my training data",
            "From my training data",
            "In my training data",
            "My training data shows",
            "My training documents show",
            "The training data indicates",
            "The training documents indicate",
            "According to my training",
            "Based on my training",
            "From my training",
            "In my training",
            "My training shows",
            "The training shows",
            "According to the training",
            "Based on the training",
            "From the training",
            "In the training",
            "The training indicates",
            "The training data shows",
            "The training documents show",
            # Additional variations
            "Based on my training documents:",
            "According to my training data:",
            "Based on the documents I've been trained on:",
            "From my training data:",
            "In my training data:",
            "My training data shows:",
            "My training documents show:",
            "The training data indicates:",
            "The training documents indicate:",
            "According to my training:",
            "Based on my training:",
            "From my training:",
            "In my training:",
            "My training shows:",
            "The training shows:",
            "According to the training:",
            "Based on the training:",
            "From the training:",
            "In the training:",
            "The training indicates:",
            "The training data shows:",
            "The training documents show:"
        ]
        
        cleaned_text = text
        
        # Remove each unwanted phrase (case-insensitive)
        for phrase in unwanted_phrases:
            # Remove phrase at the beginning of sentences
            pattern = f"^{phrase}[,.]?\\s*"
            cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)
            
            # Remove phrase in the middle of sentences
            pattern = f"\\s*{phrase}[,.]?\\s*"
            cleaned_text = re.sub(pattern, " ", cleaned_text, flags=re.IGNORECASE)
        
        # Additional aggressive cleaning for common patterns
        # Remove "Based on my training documents:" specifically
        cleaned_text = re.sub(r'^Based on my training documents:\s*', '', cleaned_text, flags=re.IGNORECASE)
        cleaned_text = re.sub(r'\s*Based on my training documents:\s*', ' ', cleaned_text, flags=re.IGNORECASE)
        
        # Remove other common patterns
        cleaned_text = re.sub(r'^According to my training data:\s*', '', cleaned_text, flags=re.IGNORECASE)
        cleaned_text = re.sub(r'\s*According to my training data:\s*', ' ', cleaned_text, flags=re.IGNORECASE)
        
        # Clean up extra whitespace
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        
        # Remove leading/trailing punctuation that might be left behind
        cleaned_text = re.sub(r'^[.,;:\s]+', '', cleaned_text)
        cleaned_text = re.sub(r'[.,;:\s]+$', '', cleaned_text)
        
        return cleaned_text
    
    def _format_response_text(self, text):
        """
        Format response text for better readability
        """
        if not text:
            return text
        
        formatted_text = text
        
        # Format plan information with proper structure
        formatted_text = self._format_plan_information(formatted_text)
        
        # Format numbered lists and steps
        formatted_text = self._format_numbered_lists(formatted_text)
        
        # Format bullet points and tips
        formatted_text = self._format_bullet_points(formatted_text)
        
        # Add line breaks for better readability
        formatted_text = self._add_proper_line_breaks(formatted_text)
        
        # Clean up extra whitespace but preserve line breaks
        # Only collapse multiple spaces/tabs, not newlines
        formatted_text = re.sub(r'[ \t]+', ' ', formatted_text)
        # Clean up multiple consecutive newlines
        formatted_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', formatted_text)
        
        return formatted_text
    
    def _format_plan_information(self, text):
        """
        Format plan information with proper structure
        """
        formatted_text = text
        
        # Handle the specific case we're seeing - convert to JSON table format
        has_plan_name = "Plan Name:" in formatted_text
        has_plan_price = "Plan Price" in formatted_text or "Plan Price -" in formatted_text
        
        print(f" DEBUG: Plan formatting check - Plan Name: {has_plan_name}, Plan Price: {has_plan_price}")
        
        if has_plan_name and has_plan_price:
            print(" DEBUG: Converting to JSON table format...")
            formatted_text = self._convert_plans_to_json_table(formatted_text)
            print(f" DEBUG: JSON conversion result: {formatted_text[:100]}...")
        else:
            print(" DEBUG: Using fallback formatting...")
            # Add line breaks before each plan section
            formatted_text = re.sub(r'(\w+ Plan Name)', r'\n\n<h3>\1</h3>', formatted_text)
            
            # Format plan details with proper labels
            formatted_text = re.sub(r'Plan Name:\s*([^P]+?)(?=Plan Price|Plan Purpose|Plan Features|$)', r'<b>Plan Name:</b> \1\n', formatted_text)
            formatted_text = re.sub(r'Plan Price\s*-\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', r'<b>Plan Price:</b> \1\n', formatted_text)
            formatted_text = re.sub(r'Plan Purpose\s*-\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', r'<b>Plan Purpose:</b> \1\n', formatted_text)
            formatted_text = re.sub(r'Plan Features\s*-\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', r'<b>Plan Features:</b>\n\1\n', formatted_text)
            
            # Format features lists (pipe-separated) with bullet points
            formatted_text = re.sub(r'([^|]+)\|([^|]+)', r'\1\n• \2', formatted_text)
        
        return formatted_text
    
    def _convert_plans_to_json_table(self, text):
        """
        Convert plan information to JSON table format for better display
        """
        import json
        
        # Extract plan information using regex
        plans = []
        
        # Find all plan sections - improved regex
        plan_sections = re.findall(r'(\w+ Plan Name[^P]+?)(?=\w+ Plan Name|$)', text, re.DOTALL)
        
        # If the above doesn't work, try a different approach
        if not plan_sections:
            # Split by plan names and process each section
            plan_parts = re.split(r'(\w+ Plan Name)', text)
            for i in range(1, len(plan_parts), 2):
                if i + 1 < len(plan_parts):
                    plan_name = plan_parts[i]
                    plan_content = plan_parts[i + 1]
                    plan_sections.append(plan_name + plan_content)
        
        for section in plan_sections:
            plan = {}
            
            # Extract plan name - more flexible pattern
            name_match = re.search(r'Plan Name:\s*([^P]+?)(?=Plan Price|Plan Purpose|Plan Features|$)', section)
            if name_match:
                plan['Plan'] = name_match.group(1).strip()
            else:
                # Try alternative pattern
                name_match = re.search(r'Plan Name\s*-\s*([^P]+?)(?=Plan Price|Plan Purpose|Plan Features|$)', section)
                if name_match:
                    plan['Plan'] = name_match.group(1).strip()
            
            # Extract plan price - more flexible pattern
            price_match = re.search(r'Plan Price\s*-\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', section)
            if price_match:
                plan['Price'] = price_match.group(1).strip()
            else:
                # Try alternative pattern
                price_match = re.search(r'Plan Price:\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', section)
                if price_match:
                    plan['Price'] = price_match.group(1).strip()
            
            # Extract plan purpose - more flexible pattern
            purpose_match = re.search(r'Plan Purpose\s*-\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', section)
            if purpose_match:
                plan['Purpose'] = purpose_match.group(1).strip()
            else:
                # Try alternative pattern
                purpose_match = re.search(r'Plan Purpose:\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', section)
                if purpose_match:
                    plan['Purpose'] = purpose_match.group(1).strip()
            
            # Extract plan features - more flexible pattern
            features_match = re.search(r'Plan Features\s*-\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', section)
            if features_match:
                features_text = features_match.group(1).strip()
                # Convert pipe-separated features to a list
                features_list = [f.strip() for f in features_text.split('|') if f.strip()]
                plan['Features'] = ', '.join(features_list)
            else:
                # Try alternative pattern
                features_match = re.search(r'Plan Features:\s*([^P]+?)(?=Plan Name|Plan Price|Plan Purpose|Plan Features|$)', section)
                if features_match:
                    features_text = features_match.group(1).strip()
                    # Convert pipe-separated features to a list
                    features_list = [f.strip() for f in features_text.split('|') if f.strip()]
                    plan['Features'] = ', '.join(features_list)
            
            if plan:  # Only add if we found plan data
                plans.append(plan)
        
        if plans:
            # Return JSON table format
            try:
                json_table = json.dumps(plans, indent=2)
                return f"Here are the available plans:\n\n{json_table}"
            except Exception as e:
                print(f" DEBUG: Error creating JSON table: {e}")
                # Fallback to original formatting
                return text
        else:
            # Fallback to original formatting
            return text
    
    def _format_numbered_lists(self, text):
        """
        Format numbered lists and steps for better readability
        """
        formatted_text = text
        
        # Format numbered steps (1), 2), 3), etc.)
        formatted_text = re.sub(r'(\d+)\)\s*([^0-9]+?)(?=\d+\)|$)', r'\n\n<b>Step \1:</b> \2\n', formatted_text)
        
        # Format numbered lists (1., 2., 3., etc.)
        formatted_text = re.sub(r'(\d+)\.\s*([^0-9]+?)(?=\d+\.|$)', r'\n\n<b>Step \1:</b> \2\n', formatted_text)
        
        # Format numbered items with dashes
        formatted_text = re.sub(r'(\d+)\s*-\s*([^0-9]+?)(?=\d+\s*-|$)', r'\n\n<b>Step \1:</b> \2\n', formatted_text)
        
        return formatted_text
    
    def _format_bullet_points(self, text):
        """
        Format bullet points and tips for better readability
        """
        formatted_text = text
        
        # Format tips (- Tip:)
        formatted_text = re.sub(r'-\s*Tip:\s*([^-\n]+)', r'\n\n💡 <b>Tip:</b> \1\n', formatted_text)
        
        # Format bullet points (- item) - but be more careful about when to apply
        # Only format if it's clearly a bullet point (not part of a sentence)
        formatted_text = re.sub(r'•\s*([^•\n]+?)(?=•|$)', r'\n\n• \1\n', formatted_text)
        
        # Format what happens next sections
        formatted_text = re.sub(r'What happens next[^:]*:\s*([^-\n]+)', r'\n\n<b>What happens next:</b>\n\1\n', formatted_text)
        
        # Format support sections
        formatted_text = re.sub(r'Support:\s*([^-\n]+)', r'\n\n<b>Support:</b>\n\1\n', formatted_text)
        
        # Format "Tips" sections
        formatted_text = re.sub(r'Tips\s*•\s*([^•]+?)(?=•|Need help|$)', r'\n\n<b>Tips:</b>\n• \1\n', formatted_text)
        
        # Format "Need help" sections
        formatted_text = re.sub(r'Need help[^?]*\?\s*•\s*([^•]+?)(?=•|$)', r'\n\n<b>Need help right now?</b>\n• \1\n', formatted_text)
        
        return formatted_text
    
    def _add_proper_line_breaks(self, text):
        """
        Add proper line breaks for better readability
        """
        # Clean up multiple line breaks
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        
        # Ensure proper spacing around sections
        text = re.sub(r'## (\w+ Plan Name)', r'\n## \1\n', text)
        
        # Add line breaks before important sections
        text = re.sub(r'(Want me to walk you through)', r'\n\n\1', text)
        text = re.sub(r'(I can guide you through)', r'\n\n\1', text)
        text = re.sub(r'(Need help right now)', r'\n\n\1', text)
        
        # Add line breaks before questions
        text = re.sub(r'(\?)\s*([A-Z])', r'\1\n\n\2', text)
        
        # Add line breaks after steps
        text = re.sub(r'(<b>Step \d+:</b>[^•]+?)(?=<b>Step)', r'\1\n', text)
        
        # Add line breaks before bullet points that aren't already formatted
        text = re.sub(r'([^•\n])\s*•\s*([^•\n]+)', r'\1\n\n• \2', text)
        
        return text
    
    def clear_conversation_context(self, conversation_id):
        """
        Clear conversation context for a specific conversation
        """
        if conversation_id in self.conversation_contexts:
            del self.conversation_contexts[conversation_id]
            print(f" DEBUG: Cleared conversation context for {conversation_id}")
    
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
            "Hello! I'm here to help. What would you like to know?",
            "Hi there!  How can I assist you?",
            "Hey! I'm ready to help.What can I help you with?",
            "Good day! I'm here to provide information. What would you like to learn about?",
        ]
        return random.choice(responses) 