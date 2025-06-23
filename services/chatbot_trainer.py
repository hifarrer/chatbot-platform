import os
import pickle
import json

# Optional imports for AI functionality
try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    print("⚠️ WARNING: AI libraries not available. Using OpenAI-only mode.")

class ChatbotTrainer:
    def __init__(self):
        if AI_AVAILABLE:
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
        else:
            self.model = None
        self.data_dir = 'training_data'
        os.makedirs(self.data_dir, exist_ok=True)
    
    def train_chatbot(self, chatbot_id, text):
        """
        Train a chatbot with the provided text by creating embeddings
        """
        print(f"🤖 DEBUG: Starting training for chatbot {chatbot_id}")
        print(f"📄 DEBUG: Text length: {len(text)} characters")
        
        # Split text into sentences/chunks for better granular responses
        sentences = self._split_into_sentences(text)
        
        # Remove empty sentences
        sentences = [s.strip() for s in sentences if s.strip()]
        
        print(f"📝 DEBUG: Split into {len(sentences)} sentences")
        for i, sentence in enumerate(sentences[:5]):  # Show first 5 sentences
            print(f"   {i+1}. {sentence[:100]}...")
        
        if not sentences:
            raise ValueError("No content found to train the chatbot")
        
        # Save training data
        training_data = {
            'sentences': sentences
        }
        
        # Generate embeddings only if AI libraries are available
        if AI_AVAILABLE and self.model:
            print("🧠 DEBUG: Generating embeddings...")
            embeddings = self.model.encode(sentences)
            print(f"✅ DEBUG: Generated embeddings shape: {embeddings.shape}")
            training_data['embeddings'] = embeddings.tolist()
        else:
            print("⚠️ DEBUG: Skipping embeddings generation (OpenAI-only mode)")
            training_data['embeddings'] = None
        
        file_path = os.path.join(self.data_dir, f'chatbot_{chatbot_id}.json')
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(training_data, f, ensure_ascii=False, indent=2)
        
        print(f"💾 DEBUG: Saved training data to {file_path}")
        print(f"✅ DEBUG: Chatbot {chatbot_id} trained with {len(sentences)} sentences")
    
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
        
        print(f"📝 DEBUG: Sentence splitting - Original: {len(sentences)}, Cleaned: {len(cleaned_sentences)}, Final: {len(final_sentences)}")
        
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
        Load training data for a specific chatbot
        """
        file_path = os.path.join(self.data_dir, f'chatbot_{chatbot_id}.json')
        
        if not os.path.exists(file_path):
            print(f"❌ DEBUG: Training file not found: {file_path}")
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Convert embeddings back to numpy array if available
            if data.get('embeddings') and AI_AVAILABLE:
                data['embeddings'] = np.array(data['embeddings'])
            
            print(f"✅ DEBUG: Loaded training data: {len(data['sentences'])} sentences")
            return data
        except Exception as e:
            print(f"❌ DEBUG: Error loading training data: {e}")
            return None
    
    def delete_chatbot_data(self, chatbot_id):
        """
        Delete training data for a specific chatbot
        """
        file_path = os.path.join(self.data_dir, f'chatbot_{chatbot_id}.json')
        
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"🗑️ DEBUG: Training data for chatbot {chatbot_id} deleted")
    
    def find_similar_content(self, chatbot_id, query, top_k=3):
        """
        Find the most similar content to the user query
        """
        print(f"🔍 DEBUG: Searching for similar content to: '{query}'")
        
        training_data = self.get_training_data(chatbot_id)
        
        if not training_data:
            print("❌ DEBUG: No training data available")
            return []
        
        # If AI libraries are not available or no embeddings, use simple text matching
        if not AI_AVAILABLE or not training_data.get('embeddings') or not self.model:
            print("⚠️ DEBUG: Using simple text matching (no embeddings available)")
            return self._simple_text_search(training_data['sentences'], query, top_k)
        
        # Encode the query
        query_embedding = self.model.encode([query])
        
        # Calculate similarities
        similarities = cosine_similarity(query_embedding, training_data['embeddings'])[0]
        
        print(f"📊 DEBUG: Similarity scores - min: {similarities.min():.3f}, max: {similarities.max():.3f}, avg: {similarities.mean():.3f}")
        
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
        
        print(f"🎯 DEBUG: Returning {len(results)} similar content items")
        return results
    
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
        
        results = []
        for idx, sentence in enumerate(sentences):
            sentence_words = set(sentence.lower().split())
            
            # Calculate simple word overlap
            overlap = len(query_words.intersection(sentence_words))
            if overlap > 0:
                # Simple scoring based on word overlap and sentence length
                score = overlap / (len(query_words) + len(sentence_words) - overlap)
                results.append({
                    'content': sentence,
                    'similarity': score,
                    'index': idx
                })
        
        # Sort by score and return top k
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:top_k]
    
    def generate_response(self, chatbot_id, user_message):
        """
        Generate a response for the user message using trained data
        """
        print(f"🤖 DEBUG: Generating response for: '{user_message}'")
        
        # Find similar content
        similar_content = self.find_similar_content(chatbot_id, user_message, top_k=3)
        
        if not similar_content:
            return "I'm sorry, I don't have enough information to answer that question. Please try rephrasing or ask something else."
        
        # Use the most similar content as the response
        best_match = similar_content[0]
        response = best_match['content']
        
        print(f"✅ DEBUG: Best match similarity: {best_match['similarity']:.3f}")
        print(f"📝 DEBUG: Response: {response[:100]}...")
        
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