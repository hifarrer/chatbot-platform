import os
import pickle
import json
from openai import OpenAI

# Optional imports for AI functionality
try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    print("WARNING: AI libraries not available. Using OpenAI-only mode.")

class ChatbotTrainer:
    def __init__(self):
        if AI_AVAILABLE:
            try:
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                print("DEBUG: SentenceTransformer model loaded successfully")
            except Exception as e:
                print(f"DEBUG: Failed to load SentenceTransformer: {e}")
                self.model = None
        else:
            print("DEBUG: AI libraries not available, using text-based search only")
            self.model = None
        # Use absolute path to ensure we're always looking in the right directory
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'training_data')
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Initialize OpenAI client for knowledge base generation
        self.api_key = os.getenv('OPENAI_API_KEY')
        if self.api_key:
            self.openai_client = OpenAI(api_key=self.api_key)
        else:
            self.openai_client = None
            print("WARNING: OPENAI_API_KEY not found. Knowledge base generation will not be available.")
    
    def generate_knowledge_base(self, text, chatbot_info=None):
        """
        Use OpenAI to convert raw document text into a structured JSON knowledge base.
        
        IMPORTANT: This method generates a knowledge base ONLY from the provided document text.
        It does NOT use any sample data or templates - only the structure format is specified.
        The sample_knowledge_base.json file is for reference/documentation only and is NEVER loaded or used.
        
        Args:
            text (str): The document text to convert (from uploaded documents only)
            chatbot_info (dict): Chatbot metadata (name, description)
            
        Returns:
            dict: Structured knowledge base generated from the document text
        """
        if not self.openai_client:
            raise ValueError("OpenAI client not initialized. Please set OPENAI_API_KEY.")
        
        print(f" DEBUG: Generating knowledge base from {len(text)} characters of text")
        print(f" DEBUG: Using ONLY the provided document text - no sample data will be used")
        
        # Create the prompt for OpenAI to generate the knowledge base
        brand_name = chatbot_info.get('name', 'the business') if chatbot_info else 'the business'
        brand_desc = chatbot_info.get('description', '') if chatbot_info else ''
        
        prompt = f"""You are an AI assistant that converts raw document text into a structured JSON knowledge base for a chatbot.

The chatbot is for: {brand_name}
Description: {brand_desc}

CRITICAL INSTRUCTIONS:
- You MUST extract information ONLY from the document text provided below
- DO NOT use any example data, sample data, or placeholder information
- DO NOT invent or fabricate any information not present in the documents
- If the documents don't contain certain information, omit those sections or use minimal placeholder text
- All kb_facts and qa_patterns must be derived exclusively from the actual document content

Convert the following document text into a structured JSON knowledge base that the chatbot can use to answer questions.

The JSON should follow this exact structure (but use ONLY data from the documents, not this example structure):
{{
  "version": "1.0",
  "brand": {{
    "name": "Business Name",
    "mission": "Mission statement",
    "target_audience": "Target audience description"
  }},
  "routing_hints": {{
    "global_keywords": ["keyword1", "keyword2", "..."],
    "urls": {{
      "page_name": "/url-path"
    }}
  }},
  "kb_facts": [
    {{
      "id": "unique-id",
      "title": "Fact title or question",
      "keywords": ["keyword1", "keyword2"],
      "answer_short": "Brief answer",
      "answer_long": "Detailed answer"
    }}
  ],
  "qa_patterns": [
    {{
      "intent_id": "unique-intent-id",
      "triggers": ["question variation 1", "question variation 2"],
      "response_inline": "Direct answer text",
      "response_ref": "kb_facts id to reference (optional)"
    }}
  ]
}}

Important guidelines:
1. Extract all important information ONLY from the document text below
2. Create comprehensive kb_facts entries for key concepts, features, prices, plans, etc. found in the documents
3. Generate qa_patterns for common questions users might ask based on the document content
4. Include relevant keywords for each fact to help with matching
5. Provide both short and long answers for flexibility
6. If the document contains pricing information, create detailed entries for each plan
7. If the document contains process information (how-to, steps), structure it clearly
8. Extract any URLs or links mentioned in the documents
9. DO NOT include any sample data, placeholder data, or information from examples
10. If certain information is not in the documents, leave those sections minimal or empty

REMEMBER: Use ONLY the document text below. No external information, no sample data, no examples.

Document text to convert (THIS IS THE ONLY SOURCE OF INFORMATION):
---BEGIN DOCUMENT TEXT---
{text}
---END DOCUMENT TEXT---

Return ONLY the JSON structure with data extracted from the document text above. No additional explanation, no sample data."""

        print(" DEBUG: Sending request to OpenAI for knowledge base generation...")
        
        try:
            # Get model from settings or use default
            try:
                from app import Settings
                setting = Settings.query.filter_by(key='openai_model').first()
                model = setting.value if setting else 'gpt-4o'
            except:
                model = 'gpt-4o'
            
            print(f" DEBUG: Using OpenAI model: {model}")
            
            # Call OpenAI API
            response = self.openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert at converting documents into structured knowledge bases for chatbots."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for more consistent structure
                max_tokens=4000   # Enough for comprehensive knowledge base
            )
            
            # Extract the JSON response
            kb_json_str = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if kb_json_str.startswith('```json'):
                kb_json_str = kb_json_str[7:]
            if kb_json_str.startswith('```'):
                kb_json_str = kb_json_str[3:]
            if kb_json_str.endswith('```'):
                kb_json_str = kb_json_str[:-3]
            kb_json_str = kb_json_str.strip()
            
            print(f" DEBUG: Received knowledge base JSON: {len(kb_json_str)} characters")
            
            # Parse and validate JSON
            kb_data = json.loads(kb_json_str)
            
            print(f" DEBUG: Knowledge base generated successfully")
            print(f"   - Brand: {kb_data.get('brand', {}).get('name', 'N/A')}")
            print(f"   - KB Facts: {len(kb_data.get('kb_facts', []))}")
            print(f"   - QA Patterns: {len(kb_data.get('qa_patterns', []))}")
            print(f"   - Global Keywords: {len(kb_data.get('routing_hints', {}).get('global_keywords', []))}")
            
            return kb_data
            
        except json.JSONDecodeError as e:
            print(f" ERROR: Failed to parse JSON from OpenAI response: {e}")
            print(f" Response was: {kb_json_str[:500]}...")
            raise ValueError(f"OpenAI returned invalid JSON: {str(e)}")
        except Exception as e:
            print(f" ERROR: Failed to generate knowledge base: {e}")
            raise
    
    def train_chatbot(self, chatbot_id, text, use_knowledge_base=True, chatbot_info=None):
        """
        Train a chatbot with the provided text.
        
        If use_knowledge_base=True (default), uses OpenAI to convert text into structured JSON knowledge base.
        If use_knowledge_base=False, uses the legacy sentence-based approach with embeddings.
        """
        print(f"DEBUG: Starting training for chatbot {chatbot_id}")
        print(f"DEBUG: Text length: {len(text)} characters")
        print(f"DEBUG: Use knowledge base: {use_knowledge_base}")
        
        if use_knowledge_base and self.openai_client:
            # NEW APPROACH: Generate structured knowledge base using OpenAI
            try:
                print(" DEBUG: Using new knowledge base generation approach")
                kb_data = self.generate_knowledge_base(text, chatbot_info)
                
                # Save the knowledge base
                file_path = os.path.join(self.data_dir, f'chatbot_{chatbot_id}.json')
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(kb_data, f, ensure_ascii=False, indent=2)
                
                print(f" DEBUG: Saved knowledge base to {file_path}")
                print(f" DEBUG: Chatbot {chatbot_id} trained with knowledge base successfully")
                return
                
            except Exception as e:
                print(f" ERROR: Knowledge base generation failed: {e}")
                print(" DEBUG: Falling back to legacy sentence-based approach")
                # Fall through to legacy approach
        
        # LEGACY APPROACH: Split into sentences and generate embeddings
        print(" DEBUG: Using legacy sentence-based training approach")
        print(f"DEBUG: AI_AVAILABLE = {AI_AVAILABLE}")
        print(f"DEBUG: Model available = {self.model is not None}")
        
        # Split text into sentences/chunks for better granular responses
        sentences = self._split_into_sentences(text)
        
        # Remove empty sentences
        sentences = [s.strip() for s in sentences if s.strip()]
        
        print(f" DEBUG: Split into {len(sentences)} sentences")
        for i, sentence in enumerate(sentences[:5]):  # Show first 5 sentences
            print(f"   {i+1}. {sentence[:100]}...")
        
        if not sentences:
            raise ValueError("No content found to train the chatbot")
        
        # Save training data in legacy format
        training_data = {
            'sentences': sentences,
            'legacy_format': True  # Mark as legacy format
        }
        
        # Generate embeddings only if AI libraries are available
        if AI_AVAILABLE and self.model:
            print(" DEBUG: Generating embeddings...")
            try:
                embeddings = self.model.encode(sentences)
                print(f" DEBUG: Generated embeddings shape: {embeddings.shape}")
                training_data['embeddings'] = embeddings.tolist()
                print(f" DEBUG: Successfully generated {len(embeddings)} embeddings")
            except Exception as e:
                print(f" DEBUG: Error generating embeddings: {e}")
                print(" DEBUG: Falling back to no embeddings")
                training_data['embeddings'] = None
        else:
            print(" DEBUG: Skipping embeddings generation")
            print(f"   - AI_AVAILABLE: {AI_AVAILABLE}")
            print(f"   - Model available: {self.model is not None}")
            training_data['embeddings'] = None
        
        file_path = os.path.join(self.data_dir, f'chatbot_{chatbot_id}.json')
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(training_data, f, ensure_ascii=False, indent=2)
        
        print(f" DEBUG: Saved training data to {file_path}")
        print(f" DEBUG: Chatbot {chatbot_id} trained with {len(sentences)} sentences (legacy format)")
    
    def _split_into_sentences(self, text):
        """
        Split text into sentences for better granularity
        """
        import re
        
        # First, clean up the text - replace multiple spaces and normalize line breaks
        text = re.sub(r'\s+', ' ', text)  # Replace multiple whitespace with single space
        text = text.replace('\n', ' ').replace('\r', ' ')  # Replace line breaks with spaces
        
        # Split on sentence endings, but be smarter about it
        # Look for periods, exclamation marks, and question marks followed by whitespace or end of string
        sentences = re.split(r'[.!?]+(?:\s+|$)', text)
        
        # Also try to split on double line breaks (paragraph breaks) if they exist in original
        # But first let's work with what we have
        
        # Clean up sentences
        cleaned_sentences = []
        current_sentence = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            
            # Skip very short fragments
            if len(sentence) < 5:
                continue
            
            # If this looks like a continuation of the previous sentence, combine them
            if (current_sentence and 
                not sentence[0].isupper() and 
                not current_sentence.endswith(('.', '!', '?')) and
                len(current_sentence) < 200):  # Don't let sentences get too long
                current_sentence += " " + sentence
            else:
                # Save the previous sentence if it exists
                if current_sentence and len(current_sentence) > 10:
                    cleaned_sentences.append(current_sentence)
                current_sentence = sentence
        
        # Don't forget the last sentence
        if current_sentence and len(current_sentence) > 10:
            cleaned_sentences.append(current_sentence)
        
        # Second pass: try to identify and merge Q&A pairs that got split
        final_sentences = []
        i = 0
        while i < len(cleaned_sentences):
            sentence = cleaned_sentences[i]
            
            # If this is a question and the next sentence looks like an answer
            if (self._looks_like_question(sentence) and 
                i + 1 < len(cleaned_sentences) and
                not self._looks_like_question(cleaned_sentences[i + 1]) and
                len(sentence + " " + cleaned_sentences[i + 1]) < 300):  # Reasonable length limit
                
                # Keep them separate but ensure the answer is complete
                final_sentences.append(sentence)
                
                # Make sure the answer is complete
                answer = cleaned_sentences[i + 1]
                # If the answer seems cut off, try to extend it
                if (i + 2 < len(cleaned_sentences) and 
                    not self._looks_like_question(cleaned_sentences[i + 2]) and
                    len(answer + " " + cleaned_sentences[i + 2]) < 400):
                    answer += " " + cleaned_sentences[i + 2]
                    i += 1  # Skip the next sentence since we merged it
                
                final_sentences.append(answer)
                i += 2
            else:
                final_sentences.append(sentence)
                i += 1
        
        print(f" DEBUG: Sentence splitting - Original: {len(sentences)}, Cleaned: {len(cleaned_sentences)}, Final: {len(final_sentences)}")
        
        return final_sentences
    
    def _looks_like_question(self, text):
        """
        Check if text looks like a question
        """
        text = text.strip().lower()
        
        question_starters = [
            'what', 'how', 'why', 'when', 'where', 'which', 'who', 'whom',
            'can', 'could', 'would', 'do', 'does', 'did', 'is', 'are', 
            'was', 'were', 'will', 'should'
        ]
        
        starts_with_question = any(text.startswith(starter) for starter in question_starters)
        ends_with_question_mark = text.endswith('?')
        
        return starts_with_question or ends_with_question_mark
    
    def get_training_data(self, chatbot_id):
        """
        Load training data for a specific chatbot.
        Returns either knowledge base format or legacy sentence-based format.
        """
        file_path = os.path.join(self.data_dir, f'chatbot_{chatbot_id}.json')
        
        print(f"DEBUG: Looking for training data at: {file_path}")
        print(f"DEBUG: Data directory exists: {os.path.exists(self.data_dir)}")
        print(f"DEBUG: Training file exists: {os.path.exists(file_path)}")
        
        if not os.path.exists(file_path):
            print(f" DEBUG: Training file not found: {file_path}")
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check if this is knowledge base format or legacy format
            if 'kb_facts' in data or 'qa_patterns' in data:
                print(f" DEBUG: Loaded knowledge base format")
                print(f"   - KB Facts: {len(data.get('kb_facts', []))}")
                print(f"   - QA Patterns: {len(data.get('qa_patterns', []))}")
                return data
            else:
                # Legacy format
                print(f" DEBUG: Loaded legacy training data: {len(data.get('sentences', []))} sentences")
                
                # Convert embeddings back to numpy array if available
                embeddings_data = data.get('embeddings')
                if embeddings_data is not None and len(embeddings_data) > 0 and AI_AVAILABLE:
                    data['embeddings'] = np.array(embeddings_data)
                    print(f" DEBUG: Loaded {len(embeddings_data)} embeddings")
                else:
                    print(f" DEBUG: No embeddings available")
                
                return data
        except Exception as e:
            print(f" DEBUG: Error loading training data: {e}")
            return None
    
    def is_knowledge_base_format(self, training_data):
        """
        Check if training data is in knowledge base format or legacy format
        """
        if not training_data:
            return False
        return 'kb_facts' in training_data or 'qa_patterns' in training_data
    
    def query_knowledge_base(self, chatbot_id, user_query, top_k=3):
        """
        Query the knowledge base for relevant information based on user query.
        Returns matching facts and QA patterns.
        """
        training_data = self.get_training_data(chatbot_id)
        
        if not training_data:
            print(" DEBUG: No training data available")
            return None
        
        if not self.is_knowledge_base_format(training_data):
            print(" DEBUG: Training data is in legacy format, not knowledge base")
            return None
        
        print(f" DEBUG: Querying knowledge base for: '{user_query}'")
        
        # Extract components from knowledge base
        kb_facts = training_data.get('kb_facts', [])
        qa_patterns = training_data.get('qa_patterns', [])
        global_keywords = training_data.get('routing_hints', {}).get('global_keywords', [])
        
        # Normalize user query
        query_lower = user_query.lower().strip()
        query_words = set(query_lower.split())
        
        # Match against QA patterns first (most specific)
        qa_matches = []
        for pattern in qa_patterns:
            intent_id = pattern.get('intent_id', '')
            triggers = pattern.get('triggers', [])
            
            # Check if any trigger matches the query
            for trigger in triggers:
                trigger_lower = trigger.lower()
                # Calculate match score
                trigger_words = set(trigger_lower.split())
                word_overlap = len(query_words.intersection(trigger_words))
                
                # Exact phrase match gets highest score
                if query_lower in trigger_lower or trigger_lower in query_lower:
                    match_score = 1.0
                elif word_overlap >= len(query_words) * 0.6:  # 60% word overlap
                    match_score = 0.7 + (word_overlap / len(query_words)) * 0.3
                elif word_overlap > 0:
                    match_score = word_overlap / max(len(query_words), len(trigger_words))
                else:
                    continue
                
                qa_matches.append({
                    'type': 'qa_pattern',
                    'intent_id': intent_id,
                    'trigger': trigger,
                    'score': match_score,
                    'response_inline': pattern.get('response_inline'),
                    'response_ref': pattern.get('response_ref'),
                    'data': pattern
                })
                print(f"   QA Pattern match: {intent_id} (score: {match_score:.3f})")
                break  # Only count one match per pattern
        
        # Match against KB facts (broader knowledge)
        kb_matches = []
        for fact in kb_facts:
            fact_id = fact.get('id', '')
            title = fact.get('title', '')
            keywords = fact.get('keywords', [])
            
            # Calculate match score based on keywords and title
            match_score = 0.0
            
            # Check title match
            title_lower = title.lower()
            if query_lower in title_lower or title_lower in query_lower:
                match_score += 0.5
            else:
                title_words = set(title_lower.split())
                title_overlap = len(query_words.intersection(title_words))
                if title_overlap > 0:
                    match_score += (title_overlap / len(query_words)) * 0.3
            
            # Check keyword matches
            keyword_matches = 0
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in query_lower or any(kw in keyword_lower for kw in query_words):
                    keyword_matches += 1
            
            if keyword_matches > 0:
                match_score += (keyword_matches / len(keywords)) * 0.5
            
            if match_score > 0.1:  # Only include if there's some match
                kb_matches.append({
                    'type': 'kb_fact',
                    'fact_id': fact_id,
                    'title': title,
                    'score': match_score,
                    'answer_short': fact.get('answer_short'),
                    'answer_long': fact.get('answer_long'),
                    'keywords': keywords,
                    'data': fact
                })
                print(f"   KB Fact match: {fact_id} (score: {match_score:.3f})")
        
        # Combine and sort all matches by score
        all_matches = qa_matches + kb_matches
        all_matches.sort(key=lambda x: x['score'], reverse=True)
        
        # Return top k matches
        top_matches = all_matches[:top_k]
        
        print(f" DEBUG: Found {len(all_matches)} total matches, returning top {len(top_matches)}")
        
        return {
            'matches': top_matches,
            'brand': training_data.get('brand', {}),
            'routing_hints': training_data.get('routing_hints', {})
        }
    
    def diagnose_training_data(self, chatbot_id):
        """
        Diagnose training data issues for a specific chatbot
        """
        print(f" DIAGNOSING TRAINING DATA FOR CHATBOT {chatbot_id}")
        print("=" * 50)
        
        file_path = os.path.join(self.data_dir, f'chatbot_{chatbot_id}.json')
        
        if not os.path.exists(file_path):
            print(f" Training file does not exist: {file_path}")
            return False
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f" Training data statistics:")
            print(f"   - Sentences: {len(data.get('sentences', []))}")
            print(f"   - Embeddings: {data.get('embeddings') is not None}")
            
            if data.get('embeddings'):
                print(f"   - Embeddings count: {len(data['embeddings'])}")
            else:
                print(f"   -  No embeddings found - this will cause poor search results")
            
            print(f" AI Library status:")
            print(f"   - AI_AVAILABLE: {AI_AVAILABLE}")
            print(f"   - Model loaded: {self.model is not None}")
            
            if not AI_AVAILABLE:
                print(f"   -  AI libraries not available - install with: pip install sentence-transformers scikit-learn numpy")
            
            if not self.model:
                print(f"   -  Model not loaded - embeddings cannot be generated")
            
            return True
            
        except Exception as e:
            print(f" Error reading training data: {e}")
            return False
    
    def delete_chatbot_data(self, chatbot_id):
        """
        Delete training data for a specific chatbot
        """
        file_path = os.path.join(self.data_dir, f'chatbot_{chatbot_id}.json')
        
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f" DEBUG: Training data for chatbot {chatbot_id} deleted")
    
    def find_similar_content(self, chatbot_id, query, top_k=3):
        """
        Find the most similar content to the user query
        """
        print(f" DEBUG: Searching for similar content to: '{query}'")
        print(f" DEBUG: AI_AVAILABLE = {AI_AVAILABLE}")
        print(f" DEBUG: Model available = {self.model is not None}")
        
        training_data = self.get_training_data(chatbot_id)
        
        if not training_data:
            print(" DEBUG: No training data available")
            return []
        
        print(f" DEBUG: Training data has {len(training_data['sentences'])} sentences")
        
        # Check embeddings availability
        embeddings = training_data.get('embeddings')
        print(f" DEBUG: Embeddings available: {embeddings is not None}")
        if embeddings is not None:
            print(f" DEBUG: Embeddings length: {len(embeddings)}")
        
        # If AI libraries are not available or no embeddings, use simple text matching
        if not AI_AVAILABLE or embeddings is None or len(embeddings) == 0 or not self.model:
            print(" DEBUG: Using simple text matching (no embeddings available)")
            print(f"   - AI_AVAILABLE: {AI_AVAILABLE}")
            print(f"   - Embeddings: {embeddings is not None}")
            print(f"   - Model: {self.model is not None}")
            return self._simple_text_search(training_data['sentences'], query, top_k)
        
        try:
            # Encode the query
            print(" DEBUG: Encoding query with model...")
            query_embedding = self.model.encode([query])
            print(f" DEBUG: Query encoded, shape: {query_embedding.shape}")
            
            # Calculate similarities
            print(" DEBUG: Calculating cosine similarities...")
            similarities = cosine_similarity(query_embedding, training_data['embeddings'])[0]
            
            print(f" DEBUG: Similarity scores - min: {similarities.min():.3f}, max: {similarities.max():.3f}, avg: {similarities.mean():.3f}")
            
            # Get top k most similar sentences
            top_indices = np.argsort(similarities)[::-1][:top_k]
            
            results = []
            for idx in top_indices:
                similarity_score = similarities[idx]
                if similarity_score > 0.1:  # Very low threshold to catch more potential matches
                    results.append({
                        'content': training_data['sentences'][idx],
                        'similarity': float(similarity_score),
                        'index': int(idx)  # Add the sentence index
                    })
                    print(f"   Match {len(results)}: {similarity_score:.3f} - {training_data['sentences'][idx][:100]}...")
            
            print(f" DEBUG: Returning {len(results)} similar content items")
            return results
            
        except Exception as e:
            print(f" DEBUG: Error in similarity search: {e}")
            print(" DEBUG: Falling back to simple text matching")
            return self._simple_text_search(training_data['sentences'], query, top_k)
    
    def get_sentence_by_index(self, chatbot_id, index):
        """
        Get a specific sentence by its index
        """
        training_data = self.get_training_data(chatbot_id)
        if training_data and 0 <= index < len(training_data['sentences']):
            return training_data['sentences'][index]
        return None
    
    def get_sentences_around_index(self, chatbot_id, index, context_size=2):
        """
        Get sentences around a specific index for context
        """
        training_data = self.get_training_data(chatbot_id)
        if not training_data:
            return []
        
        sentences = training_data['sentences']
        start_idx = max(0, index - context_size)
        end_idx = min(len(sentences), index + context_size + 1)
        
        context_sentences = []
        for i in range(start_idx, end_idx):
            context_sentences.append({
                'content': sentences[i],
                'index': i,
                'is_target': i == index
            })
        
        return context_sentences 
    
    def _simple_text_search(self, sentences, query, top_k=3):
        """
        Simple text-based search when embeddings are not available
        """
        query_words = set(query.lower().split())
        query_lower = query.lower()
        
        results = []
        for idx, sentence in enumerate(sentences):
            sentence_lower = sentence.lower()
            sentence_words = set(sentence_lower.split())
            
            # Calculate different types of matches
            word_overlap = len(query_words.intersection(sentence_words))
            
            # Partial word matching (for words like "platform" matching "platforms")
            partial_matches = 0
            for q_word in query_words:
                for s_word in sentence_words:
                    if len(q_word) > 3 and (q_word in s_word or s_word in q_word):
                        partial_matches += 0.5
            
            # Substring matching
            substring_score = 0
            for q_word in query_words:
                if len(q_word) > 3 and q_word in sentence_lower:
                    substring_score += 0.3
            
            # Calculate total score
            total_matches = word_overlap + partial_matches + substring_score
            
            if total_matches > 0:
                # Improved scoring that considers sentence length and match quality
                score = total_matches / (len(query_words) + len(sentence_words) - word_overlap + 1)
                
                # Boost score for exact phrase matches
                if query_lower in sentence_lower:
                    score *= 1.5
                
                results.append({
                    'content': sentence,
                    'similarity': min(score, 1.0),  # Cap at 1.0
                    'index': idx
                })
                
                print(f" DEBUG: Simple search match {idx}: score={score:.3f}, content='{sentence[:50]}...'")
        
        # If no matches found, try even more lenient matching
        if not results:
            print(" DEBUG: No matches found, trying lenient search...")
            for idx, sentence in enumerate(sentences):
                sentence_lower = sentence.lower()
                
                # Very lenient matching - any word from query in sentence
                for q_word in query_words:
                    if len(q_word) > 2 and q_word in sentence_lower:
                        results.append({
                            'content': sentence,
                            'similarity': 0.2,  # Low but non-zero score
                            'index': idx
                        })
                        print(f" DEBUG: Lenient match {idx}: '{sentence[:50]}...'")
                        break
        
        # Sort by score and return top k
        results.sort(key=lambda x: x['similarity'], reverse=True)
        final_results = results[:top_k]
        
        print(f" DEBUG: Simple search returning {len(final_results)} results")
        return final_results
    
    def generate_response(self, chatbot_id, user_message):
        """
        Generate a response for the user message using trained data
        """
        print(f" DEBUG: Generating response for: '{user_message}'")
        
        # Find similar content
        similar_content = self.find_similar_content(chatbot_id, user_message, top_k=3)
        
        if not similar_content:
            return "I'm sorry, I don't have enough information to answer that question. Please try rephrasing or ask something else."
        
        # Use the most similar content as the response
        best_match = similar_content[0]
        response = best_match['content']
        
        print(f" DEBUG: Best match similarity: {best_match['similarity']:.3f}")
        print(f" DEBUG: Response: {response[:100]}...")
        
        # Clean up the response (remove Q: prefixes, etc.)
        response = self._clean_response(response)
        
        return response
    
    def _clean_response(self, response):
        """
        Clean up the response text
        """
        # Remove common prefixes
        prefixes_to_remove = ['Q:', 'A:', 'Question:', 'Answer:']
        
        for prefix in prefixes_to_remove:
            if response.startswith(prefix):
                response = response[len(prefix):].strip()
        
        # If it looks like a question, try to find a better answer
        if self._looks_like_question(response):
            # This is a question, not an answer - we should handle this better
            # For now, just return a generic response
            return "I found a related question in my training data, but I need more specific information to provide a proper answer."
        
        return response.strip()