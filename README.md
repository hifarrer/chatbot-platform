# 🤖 ChatBot Platform

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--3.5-orange.svg)](https://openai.com/)

### 🔗 **Smart Link Detection**

The chatbot automatically detects and converts URLs and email addresses to clickable links:

- **URLs**: `https://example.com`, `www.example.com`, `example.com` → Clickable links
- **Emails**: `user@example.com` → Clickable mailto links
- **Smart Protocol**: Automatically adds `https://` to URLs without protocols
- **Security**: External links open in new tabs with `rel="noopener noreferrer"`
- **Styling**: Links have hover effects and proper contrast for both light and dark message bubbles

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- OpenAI API key ([Get one here](https://platform.openai.com/api-keys))


```html
<script src="https://yourserver.com/static/js/chatbot-embed.js"></script>
<script>
ChatbotEmbed.init({
    embedCode: 'your-chatbot-embed-code',
    apiUrl: 'https://yourserver.com/api/chat',
    containerId: 'chatbot-container',
    title: 'Your Bot Name',
    theme: 'light'
});
</script>
<div id="chatbot-container"></div>
```

## 🏗️ Architecture

### Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite (development) / PostgreSQL (production)
- **AI**: OpenAI GPT-3.5 + Sentence Transformers
- **Frontend**: Bootstrap 5 + Vanilla JavaScript
- **File Processing**: PyPDF2, python-docx

### Project Structure

```
chatbot-platform/
├── 📄 app.py                    # Main Flask application
├── 📄 run.py                    # Application runner with dependency checking
├── 📄 requirements.txt          # Python dependencies
├── 📄 .env.example             # Environment variables template
├── 📄 .gitignore               # Git ignore rules
│
├── 📁 services/                # Business logic
│   ├── 📄 document_processor.py    # Handle PDF, DOCX, TXT files
│   ├── 📄 chatbot_trainer.py       # AI training logic
│   └── 📄 chat_service_openai.py   # OpenAI integration
│
├── 📁 templates/               # Jinja2 HTML templates
│   ├── 📄 base.html                # Base template
│   ├── 📄 index.html               # Landing page
│   ├── 📄 dashboard.html           # User dashboard
│   ├── 📄 chatbot_details.html     # Chatbot management
│   └── 📄 contact.html             # Contact page
│
├── 📁 static/                  # Static assets
│   ├── 📁 css/
│   │   └── 📄 style.css            # Custom styles
│   └── 📁 js/
│       ├── 📄 app.js               # Main JavaScript
│       └── 📄 chatbot-embed.js     # Embeddable widget
│
├── 📁 uploads/                 # User uploaded files (gitignored)
├── 📁 training_data/           # AI training data (gitignored)
└── 📁 instance/                # Database files (gitignored)
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file with these variables:

```env
# Required
OPENAI_API_KEY=your_openai_api_key_here

# Optional
SECRET_KEY=your-secret-key-change-in-production
FLASK_ENV=development
DATABASE_URL=sqlite:///chatbot_platform.db
MAX_CONTENT_LENGTH=16777216
UPLOAD_FOLDER=uploads
HOST=0.0.0.0
PORT=5000
DEBUG=True
```

## 🚀 Deployment

### Local Development
```bash
python run.py
```

### Production with Gunicorn
```bash
pip install gunicorn
gunicorn --bind 0.0.0.0:8000 app:app
```
