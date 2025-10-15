"""
Analytics Service for Chatbot Conversations
Provides comprehensive analytics on user interactions with chatbots
"""
import os
from collections import Counter
from datetime import datetime, timedelta
from openai import OpenAI
import json
import re


class AnalyticsService:
    def __init__(self):
        """Initialize the analytics service"""
        self.api_key = os.getenv('OPENAI_API_KEY')
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
        else:
            self.client = None
    
    def get_conversation_analytics(self, conversations):
        """
        Generate comprehensive analytics for a chatbot's conversations
        
        Args:
            conversations: List of Conversation objects
            
        Returns:
            dict: Analytics data including stats, top questions, keywords, etc.
        """
        if not conversations:
            return self._get_empty_analytics()
        
        # Calculate basic statistics
        total_conversations = len(conversations)
        resolved_count = sum(1 for conv in conversations if conv.response_status == 'resolved')
        resolution_rate = (resolved_count / total_conversations * 100) if total_conversations > 0 else 0
        
        # Extract user messages for analysis
        user_messages = [conv.user_message for conv in conversations]
        
        # Get most asked questions
        top_questions = self._get_top_questions(user_messages)
        
        # Get keywords using AI
        keywords = self._extract_keywords_ai(user_messages)
        
        # Get conversation trends over time
        trends = self._get_conversation_trends(conversations)
        
        # Get response status breakdown
        status_breakdown = self._get_status_breakdown(conversations)
        
        # Get conversation length stats
        avg_message_length = sum(len(msg) for msg in user_messages) / len(user_messages)
        
        # Get time-based analytics
        time_analytics = self._get_time_analytics(conversations)
        
        return {
            'total_conversations': total_conversations,
            'resolved_count': resolved_count,
            'resolution_rate': round(resolution_rate, 2),
            'top_questions': top_questions,
            'keywords': keywords,
            'trends': trends,
            'status_breakdown': status_breakdown,
            'avg_message_length': round(avg_message_length, 2),
            'time_analytics': time_analytics
        }
    
    def _get_empty_analytics(self):
        """Return empty analytics structure when no conversations exist"""
        return {
            'total_conversations': 0,
            'resolved_count': 0,
            'resolution_rate': 0,
            'top_questions': [],
            'keywords': [],
            'trends': {
                'labels': [],
                'data': []
            },
            'status_breakdown': {
                'resolved': 0,
                'active': 0,
                'pending': 0
            },
            'avg_message_length': 0,
            'time_analytics': {
                'busiest_hour': 'N/A',
                'busiest_day': 'N/A',
                'avg_response_time': 'N/A'
            }
        }
    
    def _get_top_questions(self, messages, top_n=10):
        """
        Identify the most frequently asked questions
        Uses similarity matching to group similar questions
        """
        # Normalize and clean messages
        normalized_messages = []
        for msg in messages:
            # Convert to lowercase and remove extra whitespace
            clean_msg = ' '.join(msg.lower().strip().split())
            # Remove common punctuation
            clean_msg = re.sub(r'[^\w\s?]', '', clean_msg)
            normalized_messages.append(clean_msg)
        
        # Count exact matches first
        message_counts = Counter(normalized_messages)
        
        # Get top questions with their counts
        top_questions = []
        for msg, count in message_counts.most_common(top_n):
            # Find original message (with proper capitalization)
            original_idx = normalized_messages.index(msg)
            original_msg = messages[original_idx]
            top_questions.append({
                'question': original_msg,
                'count': count,
                'percentage': round((count / len(messages)) * 100, 2)
            })
        
        return top_questions
    
    def _extract_keywords_ai(self, messages, max_keywords=20):
        """
        Extract keywords from conversations using OpenAI
        """
        if not self.client or not messages:
            return self._extract_keywords_simple(messages, max_keywords)
        
        try:
            # Combine all messages (limit to avoid token limits)
            combined_text = ' '.join(messages[:100])  # Limit to first 100 messages
            
            # Use OpenAI to extract keywords
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a data analyst. Extract the most important keywords and topics from user questions. Return only a JSON array of keywords with their relevance scores (1-100)."
                    },
                    {
                        "role": "user",
                        "content": f"Extract up to {max_keywords} keywords from these user questions. Return as JSON array with format: [{{'keyword': 'example', 'score': 85}}]. Questions:\n\n{combined_text[:3000]}"
                    }
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            result = response.choices[0].message.content.strip()
            
            # Try to parse JSON response
            try:
                # Remove markdown code blocks if present
                result = re.sub(r'```json\s*|\s*```', '', result)
                keywords = json.loads(result)
                
                # Validate and clean keywords
                if isinstance(keywords, list):
                    cleaned_keywords = []
                    for kw in keywords[:max_keywords]:
                        if isinstance(kw, dict) and 'keyword' in kw and 'score' in kw:
                            cleaned_keywords.append({
                                'keyword': str(kw['keyword']),
                                'score': int(kw['score'])
                            })
                    return cleaned_keywords
            except json.JSONDecodeError:
                pass
            
            # If AI extraction fails, fall back to simple extraction
            return self._extract_keywords_simple(messages, max_keywords)
            
        except Exception as e:
            print(f"Error in AI keyword extraction: {e}")
            return self._extract_keywords_simple(messages, max_keywords)
    
    def _extract_keywords_simple(self, messages, max_keywords=20):
        """
        Simple keyword extraction using word frequency
        Fallback method when AI is not available
        """
        # Common stop words to exclude
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'can', 'what', 'when', 'where',
            'who', 'how', 'why', 'which', 'this', 'that', 'these', 'those',
            'i', 'you', 'he', 'she', 'it', 'we', 'they', 'my', 'your', 'his',
            'her', 'its', 'our', 'their', 'me', 'him', 'us', 'them'
        }
        
        # Extract all words
        all_words = []
        for msg in messages:
            words = re.findall(r'\b[a-z]{3,}\b', msg.lower())
            all_words.extend([w for w in words if w not in stop_words])
        
        # Count word frequencies
        word_counts = Counter(all_words)
        
        # Convert to keyword format with scores
        max_count = word_counts.most_common(1)[0][1] if word_counts else 1
        keywords = []
        for word, count in word_counts.most_common(max_keywords):
            score = int((count / max_count) * 100)
            keywords.append({
                'keyword': word,
                'score': score
            })
        
        return keywords
    
    def _get_conversation_trends(self, conversations, days=30):
        """
        Get conversation trends over the last N days
        """
        # Get date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Count conversations per day
        daily_counts = {}
        for conv in conversations:
            if conv.timestamp >= start_date:
                date_key = conv.timestamp.strftime('%Y-%m-%d')
                daily_counts[date_key] = daily_counts.get(date_key, 0) + 1
        
        # Fill in missing days with 0
        current_date = start_date
        labels = []
        data = []
        
        while current_date <= end_date:
            date_key = current_date.strftime('%Y-%m-%d')
            labels.append(current_date.strftime('%b %d'))
            data.append(daily_counts.get(date_key, 0))
            current_date += timedelta(days=1)
        
        return {
            'labels': labels,
            'data': data
        }
    
    def _get_status_breakdown(self, conversations):
        """
        Get breakdown of conversation statuses
        """
        status_counts = {
            'resolved': 0,
            'active': 0,
            'pending': 0
        }
        
        for conv in conversations:
            status = conv.response_status or 'active'
            if status in status_counts:
                status_counts[status] += 1
        
        return status_counts
    
    def _get_time_analytics(self, conversations):
        """
        Get time-based analytics (busiest hours, days, etc.)
        """
        if not conversations:
            return {
                'busiest_hour': 'N/A',
                'busiest_day': 'N/A',
                'hourly_distribution': []
            }
        
        # Analyze by hour of day
        hour_counts = Counter()
        day_counts = Counter()
        
        for conv in conversations:
            hour_counts[conv.timestamp.hour] += 1
            day_counts[conv.timestamp.strftime('%A')] += 1
        
        # Find busiest times
        busiest_hour = hour_counts.most_common(1)[0][0] if hour_counts else 0
        busiest_day = day_counts.most_common(1)[0][0] if day_counts else 'N/A'
        
        # Format busiest hour
        hour_12 = busiest_hour % 12 if busiest_hour % 12 != 0 else 12
        am_pm = 'AM' if busiest_hour < 12 else 'PM'
        busiest_hour_str = f"{hour_12}:00 {am_pm}"
        
        # Create hourly distribution for chart
        hourly_distribution = []
        for hour in range(24):
            count = hour_counts.get(hour, 0)
            hour_12 = hour % 12 if hour % 12 != 0 else 12
            am_pm = 'AM' if hour < 12 else 'PM'
            hourly_distribution.append({
                'hour': f"{hour_12} {am_pm}",
                'count': count
            })
        
        return {
            'busiest_hour': busiest_hour_str,
            'busiest_day': busiest_day,
            'hourly_distribution': hourly_distribution
        }
    
    def get_question_similarity_clusters(self, messages, num_clusters=5):
        """
        Group similar questions together (future enhancement)
        This would use more advanced NLP techniques
        """
        # Placeholder for future implementation
        # Could use sentence transformers, clustering algorithms, etc.
        pass

