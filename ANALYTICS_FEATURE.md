# Chatbot Analytics Feature

## Overview
This feature provides comprehensive analytics for chatbot conversations, helping users understand how their chatbots are performing and what users are asking about.

## Features Implemented

### 1. **Analytics Dashboard**
A beautiful, interactive dashboard that displays:

#### Key Metrics (Cards)
- **Total Interactions**: Total number of conversations
- **Resolved Count**: Number of resolved conversations
- **Resolution Rate**: Percentage of conversations marked as resolved
- **Average Message Length**: Average character count of user messages

#### Visualization Charts
- **Conversation Trends**: Line chart showing conversation volume over the last 30 days
- **Status Breakdown**: Doughnut chart showing distribution of conversation statuses (resolved, active, pending)
- **Activity Patterns**: Bar chart showing hourly distribution of conversations

#### Top Questions
- List of most frequently asked questions
- Each question shows:
  - The question text
  - Number of times asked
  - Percentage of total questions
  - Visual progress bar

#### AI-Powered Keyword Cloud
- Keywords extracted using OpenAI GPT-3.5-turbo
- Visual word cloud with:
  - Size based on keyword relevance
  - Interactive hover effects
  - Color-coded importance
- Falls back to simple frequency-based extraction if OpenAI is unavailable

#### Time Analytics
- **Busiest Hour**: Most active hour of the day
- **Busiest Day**: Most active day of the week
- **Hourly Distribution**: Complete 24-hour breakdown

## Technical Implementation

### Backend Components

#### 1. **Analytics Service** (`services/analytics_service.py`)
Main service class that processes conversation data:

```python
class AnalyticsService:
    def get_conversation_analytics(conversations)
    def _get_top_questions(messages, top_n=10)
    def _extract_keywords_ai(messages, max_keywords=20)
    def _extract_keywords_simple(messages, max_keywords=20)
    def _get_conversation_trends(conversations, days=30)
    def _get_status_breakdown(conversations)
    def _get_time_analytics(conversations)
```

**Features:**
- Calculates resolution rates
- Identifies frequently asked questions
- Extracts keywords using AI
- Analyzes conversation patterns over time
- Provides time-based analytics

#### 2. **Analytics Route** (`app.py`)
New route added: `/chatbot/<int:chatbot_id>/analytics`
- Requires login
- Fetches all conversations for a chatbot
- Processes data through AnalyticsService
- Renders analytics template

### Frontend Components

#### 1. **Analytics Template** (`templates/analytics.html`)
Beautiful, responsive analytics dashboard with:
- Bootstrap 5 styling
- Chart.js integration for visualizations
- Animated cards and transitions
- Responsive design for mobile devices

**Charts Used:**
- **Chart.js 4.4.0** for all visualizations
- Line chart with gradient fill for trends
- Doughnut chart for status breakdown
- Bar chart for hourly patterns

#### 2. **Navigation Links**
Analytics links added to:
- **Dashboard** (`templates/dashboard.html`): "View Analytics" button on each chatbot card
- **Chatbot Details** (`templates/chatbot_details.html`): "View Analytics" button in header

## Data Analysis Features

### 1. **Question Similarity Matching**
- Normalizes questions by removing punctuation and extra whitespace
- Groups similar questions together
- Counts frequency of each question

### 2. **AI Keyword Extraction**
Uses OpenAI GPT-3.5-turbo to:
- Identify important topics from user questions
- Assign relevance scores (1-100) to each keyword
- Return structured JSON data

**Fallback:** Simple frequency-based keyword extraction when AI is unavailable

### 3. **Time-Based Analytics**
Analyzes conversations by:
- Hour of day (0-23)
- Day of week
- Identifies peak usage times

### 4. **Status Tracking**
Tracks conversation statuses:
- **Resolved**: Questions successfully answered
- **Active**: Ongoing conversations
- **Pending**: Awaiting response

## User Interface

### Design Principles
1. **Visual Hierarchy**: Important metrics in colorful cards at the top
2. **Interactive Charts**: Hover tooltips and animations
3. **Responsive Layout**: Works on desktop, tablet, and mobile
4. **Clean Typography**: Clear, readable text with appropriate sizing
5. **Color Coding**: Consistent color scheme for status indicators

### Animations
- Fade-in animations for cards
- Hover effects on cards and keywords
- Progress bar animations
- Chart animations on load

### Empty State
When no conversations exist:
- Friendly informational message
- Explanation that analytics will appear once users interact with the chatbot

## Access Points

Users can access analytics from:
1. **Main Dashboard**: "View Analytics" button on each chatbot card
2. **Chatbot Details Page**: "View Analytics" button in the header
3. **Direct URL**: `/chatbot/<id>/analytics`

## Performance Considerations

### Optimization
- Limits keyword extraction to first 100 messages to avoid token limits
- Caches analytics calculations (can be enhanced with Redis in future)
- Efficient database queries with proper indexing

### Scalability
- Can handle thousands of conversations
- Charts automatically adjust to data volume
- Responsive design scales to any screen size

## Future Enhancements

### Potential Improvements
1. **Date Range Filters**: Allow users to select custom date ranges
2. **Export Options**: Export analytics data to PDF or CSV
3. **Real-time Updates**: WebSocket integration for live analytics
4. **Advanced NLP**: Sentiment analysis, intent classification
5. **Comparative Analytics**: Compare multiple chatbots
6. **Custom Reports**: User-defined analytics reports
7. **Email Summaries**: Automated weekly/monthly analytics emails
8. **A/B Testing**: Compare different chatbot configurations
9. **User Segmentation**: Analyze different user groups
10. **Conversation Clustering**: Group similar conversation patterns

## Testing

The analytics service has been thoroughly tested with:
- Mock conversation data
- Empty data scenarios
- Various time ranges
- Different conversation statuses

All tests pass successfully, confirming:
- Correct calculation of metrics
- Proper keyword extraction
- Accurate time-based analytics
- Graceful handling of edge cases

## Dependencies

### Python Packages
- `openai`: For AI-powered keyword extraction
- `collections.Counter`: For frequency counting
- `datetime`: For time-based analytics

### Frontend Libraries
- **Chart.js 4.4.0**: For data visualizations
- **Bootstrap 5**: For responsive UI components
- **Font Awesome**: For icons

## Configuration

### Environment Variables
```bash
OPENAI_API_KEY=your_openai_api_key
```

The analytics feature will work with or without OpenAI API key:
- **With API key**: Advanced AI-powered keyword extraction
- **Without API key**: Simple frequency-based keyword extraction

## Usage Example

1. Navigate to your chatbot details page
2. Click "View Analytics" button
3. View comprehensive analytics dashboard with:
   - Key metrics
   - Trend charts
   - Top questions
   - Keyword cloud
   - Time-based insights

## Conclusion

This analytics feature provides users with valuable insights into how their chatbots are being used, what questions are being asked, and how well they're performing. The combination of visual charts, AI-powered analysis, and detailed breakdowns gives users everything they need to optimize their chatbots and improve user satisfaction.

