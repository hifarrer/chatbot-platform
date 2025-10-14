# Google Docs Training Feature

## Overview
Added the ability to train chatbots using Google Docs links. Users can now import training documents directly from Google Docs without downloading them first.

## Changes Made

### 1. Document Processor Enhancement (`services/document_processor.py`)
Added two new methods:
- `extract_google_doc_id(url)`: Extracts the document ID from various Google Docs URL formats
- `fetch_google_doc(url)`: Fetches text content from a publicly accessible Google Doc

**Features:**
- Supports multiple Google Docs URL formats
- Exports documents as plain text for processing
- Provides clear error messages for permission issues
- 30-second timeout for network requests

### 2. Backend Endpoint (`app.py`)
Added new route: `/upload_google_doc/<int:chatbot_id>`

**Functionality:**
- Accepts Google Docs URLs via POST request
- Fetches document content using the document processor
- Saves content as a text file in the uploads folder
- Creates/updates document records in the database
- Handles duplicate documents (updates existing ones)
- Provides user-friendly error messages

### 3. User Interface (`templates/chatbot_details.html`)
Enhanced the document upload section with a tabbed interface:
- **Upload File Tab**: Original file upload functionality
- **Google Docs Tab**: New Google Docs URL input

**UI Features:**
- Clean tabbed interface using Bootstrap
- Clear instructions for sharing permissions
- Visual indicators (Google icon)
- Placeholder example URL
- Help text explaining sharing requirements

## How to Use

### For End Users:
1. Navigate to your chatbot's details page
2. Click on the "Google Docs" tab in the Upload Training Documents section
3. Ensure your Google Doc is shared with "Anyone with the link can view"
   - In Google Docs, click "Share"
   - Change from "Restricted" to "Anyone with the link"
   - Set permission to "Viewer"
4. Copy the Google Docs URL
5. Paste the URL into the input field
6. Click "Import from Google Docs"
7. The document will be imported and ready for training

### Supported URL Formats:
- `https://docs.google.com/document/d/{DOC_ID}/edit`
- `https://docs.google.com/document/d/{DOC_ID}/`
- `https://docs.google.com/document/d/{DOC_ID}`
- `https://docs.google.com/document/u/0/d/{DOC_ID}/edit`

### Requirements:
- Google Doc must be shared with "Anyone with the link can view" permission
- Document must contain text content
- Network access to docs.google.com

## Technical Implementation

### Document Fetching Process:
1. Extract document ID from URL using regex patterns
2. Construct export URL: `https://docs.google.com/document/d/{DOC_ID}/export?format=txt`
3. Fetch content via HTTP GET request
4. Handle various HTTP status codes (200, 403, 404, etc.)
5. Save content as `.txt` file in uploads folder
6. Create database record with filename `Google_Doc_{DOC_ID}.txt`

### Error Handling:
- **Invalid URL**: Clear error message about URL format
- **403 Forbidden**: Instructions about sharing permissions
- **404 Not Found**: Document doesn't exist message
- **Network Errors**: Connection/timeout error messages
- **Empty Document**: Warning about empty content

### Database Integration:
- Documents imported from Google Docs are stored like regular uploads
- Filename format: `{UUID}_Google_Doc_{DOC_ID}.txt`
- Original filename: `Google_Doc_{DOC_ID}.txt`
- Duplicate detection based on original filename
- Automatically marked as unprocessed for training

## Dependencies
All required dependencies are already in `requirements.txt`:
- `requests>=2.31.0,<3.0.0` - For HTTP requests to fetch Google Docs

## Benefits
1. **Convenience**: No need to download and re-upload documents
2. **Collaboration**: Easier to update training data from shared documents
3. **Real-time**: Can fetch latest version of documents
4. **Integration**: Seamless integration with existing training pipeline
5. **User-friendly**: Clear UI and helpful error messages

## Future Enhancements (Optional)
- Support for Google Sheets
- Support for Google Slides
- Auto-sync feature to refresh Google Docs periodically
- OAuth integration for private documents
- Support for Google Drive folders (batch import)

