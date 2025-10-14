# Google Sheets Training Feature

## Overview
Extended the chatbot training platform to support Google Sheets as a data source. This feature is perfect for structured data like pricing plans, product catalogs, FAQs, inventory lists, and other tabular information. The sheets are automatically converted to optimized JSON format for AI training.

## Changes Made

### 1. Document Processor Enhancement (`services/document_processor.py`)
Added four new methods:
- `extract_google_sheet_id(url)`: Extracts the spreadsheet ID from Google Sheets URLs
- `fetch_google_sheet(url)`: Fetches and processes Google Sheets data
- `csv_to_structured_json(csv_text, sheet_name)`: Converts CSV to structured JSON
- `_format_sheet_for_training(structured_data)`: Formats data for optimal AI training

**Key Features:**
- Fetches sheets as CSV from Google Sheets export API
- Converts tabular data to structured JSON format
- Creates dual-format training text (JSON + human-readable)
- Handles empty rows and cleans data
- Provides detailed metadata (columns, row counts)

### 2. Backend Endpoint (`app.py`)
Added new route: `/upload_google_sheet/<int:chatbot_id>`

**Functionality:**
- Accepts Google Sheets URLs via POST request
- Fetches and converts sheet data using the document processor
- Saves formatted content as text file in uploads folder
- Creates/updates document records in the database
- Handles duplicate sheets (updates existing ones)
- Clear error messages for common issues

### 3. User Interface (`templates/chatbot_details.html`)
Added third tab to the document upload interface:
- **Upload File Tab**: Original file upload
- **Google Docs Tab**: Google Docs import
- **Google Sheets Tab**: New Google Sheets import

**UI Features:**
- Clean tabbed navigation
- Table icon for visual identification
- Helpful examples of use cases
- Instructions for sharing permissions
- Info about automatic JSON conversion
- Blue button styling to distinguish from other tabs

## How to Use

### For End Users:
1. Navigate to your chatbot's details page
2. Click on the "Google Sheets" tab
3. Ensure your Google Sheet is shared with "Anyone with the link can view"
   - In Google Sheets, click "Share"
   - Change from "Restricted" to "Anyone with the link"
   - Set permission to "Viewer"
4. Copy the Google Sheets URL
5. Paste the URL into the input field
6. Click "Import from Google Sheets"
7. The sheet will be imported, converted to JSON, and ready for training

### Supported URL Formats:
- `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`
- `https://docs.google.com/spreadsheets/d/{SHEET_ID}/`
- `https://docs.google.com/spreadsheets/d/{SHEET_ID}`
- `https://docs.google.com/spreadsheets/u/0/d/{SHEET_ID}/edit#gid=0`

### Perfect Use Cases:
- **Pricing Plans**: Plan names, prices, features, limits
- **Product Catalog**: Product names, descriptions, prices, SKUs
- **FAQ Database**: Questions, answers, categories
- **Inventory Lists**: Items, quantities, locations, status
- **Contact Information**: Names, roles, email, phone
- **Service Offerings**: Services, descriptions, pricing, availability

## Technical Implementation

### Data Processing Flow:
1. Extract spreadsheet ID from URL using regex patterns
2. Construct export URL: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0`
3. Fetch CSV data via HTTP GET request
4. Parse CSV into structured data with headers
5. Convert to JSON with metadata (columns, row count)
6. Create dual-format training text:
   - **JSON Section**: Structured data for AI to parse
   - **Human-Readable Section**: Formatted list for natural language understanding
7. Save as `.txt` file in uploads folder
8. Create database record with filename `Google_Sheet_{SHEET_ID}.txt`

### Training Text Format Example:
```
=== Google Sheet: Pricing Plans ===
Total Rows: 3
Columns: Plan Name, Price, Features, Max Chatbots

=== Structured Data (JSON Format) ===
{
  "sheet_name": "Pricing Plans",
  "columns": ["Plan Name", "Price", "Features", "Max Chatbots"],
  "row_count": 3,
  "data": [
    {
      "Plan Name": "Free Plan",
      "Price": "$0",
      "Features": "Basic features",
      "Max Chatbots": "1"
    },
    ...
  ]
}

=== Human-Readable Format ===

Entry 1:
  Plan Name: Free Plan
  Price: $0
  Features: Basic features
  Max Chatbots: 1
...
```

### Why This Format?
This dual-format approach gives OpenAI the best of both worlds:
1. **Structured JSON**: Easy for AI to parse and understand relationships
2. **Human-Readable Text**: Natural language context for conversational responses
3. **Metadata**: Column names and counts help AI understand the data structure

### Error Handling:
- **Invalid URL**: Clear error message about URL format
- **403 Forbidden**: Instructions about sharing permissions
- **404 Not Found**: Sheet doesn't exist message
- **Network Errors**: Connection/timeout error messages
- **Empty Sheet**: Warning about empty content

### Data Cleaning:
- Removes completely empty rows
- Strips whitespace from values
- Filters out empty string values
- Preserves zero values and other meaningful data

## Benefits

### For Users:
1. **No Manual Export**: Fetch data directly from Google Sheets
2. **Always Current**: Can refresh data by re-importing
3. **Easy Collaboration**: Team can update sheets; chatbot stays in sync
4. **Structured Training**: Better AI understanding of tabular data
5. **Flexibility**: Perfect for frequently updated data

### For AI Training:
1. **Structured Format**: JSON makes relationships clear
2. **Dual Representation**: Both machine and human-readable
3. **Rich Metadata**: Column headers become semantic anchors
4. **Clean Data**: Automatic filtering and cleaning
5. **Optimal for OpenAI**: Format designed for GPT models

## Example Use Case: Pricing Plans

### Google Sheet Structure:
| Plan Name    | Price      | Features           | Max Chatbots |
|--------------|------------|--------------------|--------------|
| Free Plan    | $0         | Basic features     | 1            |
| Starter Plan | $29/month  | Advanced features  | 5            |
| Pro Plan     | $99/month  | All features       | Unlimited    |

### Result:
When a user asks "What are your pricing plans?" or "How much does the Pro plan cost?", the chatbot can:
- Understand the structured data
- Compare plans accurately
- Provide specific pricing information
- List features for each tier
- Recommend appropriate plans

## Dependencies
All required dependencies are already in `requirements.txt`:
- `requests>=2.31.0,<3.0.0` - For HTTP requests
- Built-in Python libraries: `csv`, `json`, `re`, `io`

## Future Enhancements (Optional)

### Multi-Sheet Support:
- Fetch all sheets from a workbook
- Identify sheets by name (gid parameter)
- Combine multiple sheets into single training data

### Advanced Features:
- Support for formatted cells (bold, colors)
- Handle merged cells appropriately
- Preserve formulas and calculated values
- Support for cell comments/notes
- Auto-sync on schedule (refresh data periodically)

### OAuth Integration:
- Access private sheets with user authorization
- No need for public sharing
- Better security for sensitive data

### Enhanced Processing:
- Detect and handle header rows automatically
- Identify data types (numbers, dates, text)
- Create relationships between multiple sheets
- Generate summary statistics

## Comparison: Google Sheets vs Other Formats

| Feature | PDF/DOCX | Plain Text | JSON | Google Sheets |
|---------|----------|------------|------|---------------|
| Structured Data | ❌ | ❌ | ✅ | ✅ |
| Easy Updates | ❌ | ❌ | ❌ | ✅ |
| Collaboration | ❌ | ❌ | ❌ | ✅ |
| AI-Optimized | ⚠️ | ⚠️ | ✅ | ✅ |
| Direct Import | ✅ | ✅ | ✅ | ✅ |
| Tabular Data | ❌ | ❌ | ⚠️ | ✅ |

## Testing

All tests passed successfully:
- ✅ URL parsing for various Google Sheets formats
- ✅ CSV to JSON conversion
- ✅ Data formatting for training
- ✅ Empty row handling
- ✅ Invalid URL rejection
- ✅ Endpoint integration
- ✅ UI rendering

## Conclusion

The Google Sheets feature makes chatbot training significantly more powerful for structured data. It's perfect for businesses that maintain their information in spreadsheets and want their chatbots to access that data without manual conversions. The automatic JSON conversion ensures optimal AI understanding while the dual-format approach provides flexibility for different types of queries.

