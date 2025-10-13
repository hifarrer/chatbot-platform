# Knowledge Base Training System

## Overview

The chatbot platform now uses an advanced **OpenAI-powered knowledge base generation system** that converts raw document text into structured, queryable JSON knowledge bases. This provides more accurate and context-aware responses compared to the previous sentence-based approach.

## Architecture

### Previous System (Legacy)
1. Extract text from documents
2. Split text into sentences
3. Generate embeddings for each sentence
4. Find similar sentences using cosine similarity
5. Send similar sentences to OpenAI for response generation

### New System (Knowledge Base)
1. Extract text from documents
2. **Send extracted text to OpenAI to convert into structured JSON knowledge base**
3. **Store knowledge base with facts, QA patterns, and keywords**
4. **Match user queries with intents and keywords**
5. **Return pre-structured answers or send matched facts to OpenAI**

## JSON Knowledge Base Format

**IMPORTANT**: The knowledge base structure shown below is for reference only. When training a chatbot, the system generates the knowledge base **ONLY from your uploaded documents**. No sample data, template data, or placeholder information is ever used. See `TEMPLATE_knowledge_base_structure.json` for a complete structure reference.

The knowledge base follows this structure:

```json
{
  "version": "1.0",
  "brand": {
    "name": "Business Name",
    "mission": "Mission statement",
    "target_audience": "Target audience description"
  },
  "routing_hints": {
    "global_keywords": ["keyword1", "keyword2", "..."],
    "urls": {
      "page_name": "/url-path"
    }
  },
  "kb_facts": [
    {
      "id": "unique-id",
      "title": "Fact title or question",
      "keywords": ["keyword1", "keyword2"],
      "answer_short": "Brief answer",
      "answer_long": "Detailed answer"
    }
  ],
  "qa_patterns": [
    {
      "intent_id": "unique-intent-id",
      "triggers": ["question variation 1", "question variation 2"],
      "response_inline": "Direct answer text",
      "response_ref": "kb_facts id to reference (optional)"
    }
  ]
}
```

## Key Components

### 1. Brand Information
Contains metadata about the business:
- Name
- Mission statement
- Target audience

### 2. Routing Hints
Global keywords and URLs for quick reference:
- **global_keywords**: Common terms related to the business
- **urls**: Important page URLs and their paths

### 3. KB Facts (Knowledge Base Facts)
Structured information entries with:
- **id**: Unique identifier
- **title**: Descriptive title or question
- **keywords**: Array of keywords for matching
- **answer_short**: Brief answer (1-2 sentences)
- **answer_long**: Detailed answer (comprehensive explanation)

### 4. QA Patterns
Common question-answer patterns:
- **intent_id**: Unique intent identifier
- **triggers**: Array of question variations that should trigger this response
- **response_inline**: Direct answer text
- **response_ref**: Optional reference to a KB fact for more details

## How It Works

### Training Process

1. **Document Upload**: User uploads PDF, DOCX, or TXT files
2. **Text Extraction**: System extracts text from documents
3. **Knowledge Base Generation**:
   - Extracted text is sent to OpenAI (GPT-4o)
   - OpenAI analyzes the content and generates structured JSON
   - JSON includes facts, QA patterns, keywords, and metadata
4. **Storage**: Knowledge base is saved as `training_data/chatbot_{id}.json`

### Query Process

1. **User Query**: User asks a question through the chat interface
2. **Query Normalization**: Query is normalized and tokenized
3. **Intent Matching**: System checks QA patterns for matching triggers
4. **Keyword Matching**: System checks KB facts for keyword matches
5. **Scoring**: Matches are scored based on:
   - Exact phrase matches (1.0)
   - Word overlap (0.6-1.0)
   - Keyword matches (0.1-0.5)
6. **Context Building**: Top matches are assembled into context passages
7. **Response Generation**: Context is sent to OpenAI to generate final response

### Matching Algorithm

#### QA Pattern Matching
- Exact phrase match: score = 1.0
- 60%+ word overlap: score = 0.7-1.0
- Any word overlap: score proportional to overlap

#### KB Fact Matching
- Title match: +0.5 score
- Keyword matches: +0.5 score (proportional to keyword count)
- Minimum threshold: 0.1

## Benefits

### 1. Better Accuracy
- Pre-structured answers reduce hallucinations
- Intent matching provides more relevant responses
- Keyword-based search is more reliable

### 2. Faster Responses
- No need to search through thousands of sentences
- Direct answer lookup for common questions
- More efficient context building

### 3. Easier Maintenance
- Knowledge base can be manually edited if needed
- Clear structure makes it easy to understand what the chatbot knows
- Can add/remove facts without retraining

### 4. Better Context Understanding
- OpenAI understands the full document context during generation
- Creates logical groupings of related information
- Identifies common question patterns automatically

## Code Structure

### `services/chatbot_trainer.py`

#### Key Methods:

**`generate_knowledge_base(text, chatbot_info)`**
- Sends text to OpenAI for conversion
- Returns structured JSON knowledge base
- Handles JSON parsing and validation

**`train_chatbot(chatbot_id, text, use_knowledge_base=True, chatbot_info=None)`**
- Main training method
- Supports both knowledge base and legacy modes
- Saves training data to file

**`query_knowledge_base(chatbot_id, user_query, top_k=3)`**
- Queries knowledge base for relevant information
- Returns matching facts and QA patterns with scores
- Handles both QA pattern and KB fact matching

**`is_knowledge_base_format(training_data)`**
- Checks if training data is in knowledge base format
- Used to determine which query method to use

### `services/chat_service_openai.py`

#### Key Methods:

**`_get_relevant_context(chatbot_id, user_message, max_context_length=2000)`**
- Gets relevant context from training data
- Automatically detects format (knowledge base vs legacy)
- Routes to appropriate context extraction method

**`_get_context_from_knowledge_base(chatbot_id, user_message, max_context_length=2000)`**
- Extracts context from knowledge base format
- Queries knowledge base and builds context passages
- Handles both QA patterns and KB facts

## Migration from Legacy Format

The system automatically detects the format of training data:

1. **Legacy Format**: Contains `sentences` and `embeddings` keys
2. **Knowledge Base Format**: Contains `kb_facts` and `qa_patterns` keys

Both formats are supported simultaneously. When a chatbot is retrained, it will use the new knowledge base format.

### To Retrain Existing Chatbots:

1. Go to chatbot details page
2. Click "Train" button
3. System will automatically use knowledge base generation
4. Old training data will be replaced with new knowledge base

## Configuration

### Environment Variables

- `OPENAI_API_KEY`: Required for knowledge base generation
- Model is read from database settings (`openai_model` key)

### Default Settings

- **Model**: `gpt-4o` (or from settings)
- **Temperature**: `0.3` (for consistent structure)
- **Max Tokens**: `4000` (for comprehensive knowledge bases)
- **Top K Matches**: `5` (adjustable per query)

## Testing

Run the test suite to verify the knowledge base system:

```bash
python test_knowledge_base.py
```

The test suite includes:
1. **Knowledge Base Generation Test**: Tests OpenAI conversion
2. **Knowledge Base Querying Test**: Tests query matching
3. **Chat Service Integration Test**: Tests end-to-end integration

## Examples

### Example 1: Pricing Query

**User Query**: "What are your pricing plans?"

**Knowledge Base Match**:
- Intent: `plans-general`
- Trigger Match: "what are the available plans" (score: 0.85)
- Response: Full list of plans with details

### Example 2: Specific Feature Query

**User Query**: "Does the premium plan include API access?"

**Knowledge Base Match**:
- Fact: `plan-premium-details`
- Keywords: ["premium", "api", "features"]
- Response: "Yes, the Premium plan includes API access along with unlimited chatbots, 100MB uploads, priority support..."

### Example 3: How-to Query

**User Query**: "How do I embed the chatbot on my website?"

**Knowledge Base Match**:
- Intent: `embed-how`
- Trigger Match: "how to embed" (score: 1.0)
- Response: "After training, copy your embed code from the dashboard and paste it into your website..."

## Troubleshooting

### Knowledge Base Generation Fails

**Problem**: OpenAI returns invalid JSON or error

**Solutions**:
1. Check OPENAI_API_KEY is set correctly
2. Verify you have API credits available
3. Check document text is not too long (adjust if needed)
4. Review OpenAI API status for outages

**Fallback**: System automatically falls back to legacy sentence-based training

### No Matches Found

**Problem**: Query doesn't match any KB facts or QA patterns

**Solutions**:
1. Retrain chatbot to update knowledge base
2. Check if document coverage is sufficient
3. Add more training documents with relevant information
4. Manually edit knowledge base JSON if needed (advanced)

### Low Match Scores

**Problem**: Matches have low relevance scores

**Solutions**:
1. Ensure training documents are high quality
2. Retrain with more comprehensive documents
3. Check if query keywords exist in training data
4. Consider adjusting match threshold in code

## Performance Considerations

### Training Time
- **Legacy Format**: 1-5 seconds (depending on document size)
- **Knowledge Base Format**: 5-30 seconds (OpenAI API call + processing)

### Query Time
- **Legacy Format**: 100-500ms (similarity search)
- **Knowledge Base Format**: 50-200ms (keyword/intent matching)

### Storage
- **Legacy Format**: ~1-10MB per chatbot (with embeddings)
- **Knowledge Base Format**: ~50-500KB per chatbot (compressed JSON)

## Future Enhancements

### Planned Features
1. **Manual KB Editing**: Web interface for editing knowledge base
2. **KB Merging**: Combine multiple knowledge bases
3. **KB Export/Import**: Share knowledge bases between chatbots
4. **Analytics**: Track which facts are used most
5. **Auto-Update**: Automatically update KB when documents change
6. **Multi-Language**: Support for multiple languages in KB
7. **Response Templates**: Use templates for consistent formatting

### Advanced Features
1. **Entity Extraction**: Extract entities (people, places, products)
2. **Relationship Mapping**: Map relationships between facts
3. **Confidence Scoring**: Provide confidence scores for answers
4. **Fallback Chains**: Multiple levels of fallback responses
5. **Context Memory**: Remember conversation context across messages

## API Reference

### `ChatbotTrainer` Class

```python
from services.chatbot_trainer import ChatbotTrainer

trainer = ChatbotTrainer()

# Generate knowledge base from text
kb_data = trainer.generate_knowledge_base(
    text="...",
    chatbot_info={'name': 'Bot', 'description': '...'}
)

# Train chatbot with knowledge base
trainer.train_chatbot(
    chatbot_id=1,
    text="...",
    use_knowledge_base=True,
    chatbot_info={'name': 'Bot', 'description': '...'}
)

# Query knowledge base
results = trainer.query_knowledge_base(
    chatbot_id=1,
    user_query="What are your plans?",
    top_k=3
)
```

### `ChatServiceOpenAI` Class

```python
from services.chat_service_openai import ChatServiceOpenAI

chat_service = ChatServiceOpenAI()

# Get response (automatically uses KB if available)
response = chat_service.get_response(
    chatbot_id=1,
    user_message="What are your plans?",
    conversation_id="unique-id"
)

# Get relevant context from KB
context = chat_service._get_relevant_context(
    chatbot_id=1,
    user_message="What are your plans?",
    max_context_length=2000
)
```

## License

This knowledge base system is part of the Owlbee.AI Chatbot Platform.

## Support

For questions or issues:
- Review this documentation
- Run test suite: `python test_knowledge_base.py`
- Check logs for detailed debugging information
- Contact support through the platform

---

**Version**: 1.0  
**Last Updated**: 2025-10-13  
**Author**: Owlbee.AI Development Team

