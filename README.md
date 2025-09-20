# 🤖 ChatBot Platform

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--3.5-orange.svg)](https://openai.com/)

A complete AI chatbot platform that allows users to create, train, and deploy intelligent chatbots for their websites. Upload documents to train your chatbots and easily embed them anywhere with a simple code snippet.

## 🌟 Live Demo

Try the Platform Assistant chatbot on our [demo site](http://localhost:5000) - it's trained on our platform documentation and can answer questions about features, pricing, and how to get started!

## ✨ Features

- 🔐 **User Authentication** - Secure registration and login system
- 🤖 **Multiple Chatbots** - Create unlimited chatbots for different purposes  
- 📄 **Document Training** - Upload PDF, DOCX, and TXT files to train your chatbots
- 🧠 **AI-Powered Responses** - Uses OpenAI GPT-3.5 for intelligent, natural responses
- 🎨 **Easy Embedding** - Get embed code to add chatbots to any website
- 💬 **Real-time Chat** - Live chat interface with typing indicators
- 📊 **Analytics** - Track conversations and chatbot performance
- 📱 **Responsive Design** - Works perfectly on desktop and mobile devices
- 🚀 **Drag & Drop Upload** - Intuitive file upload interface
- ⚡ **Fast Training** - Quick document processing and chatbot training

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- OpenAI API key ([Get one here](https://platform.openai.com/api-keys))

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/chatbot-platform.git
   cd chatbot-platform
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv chatbot_env
   
   # Windows
   chatbot_env\Scripts\activate
   
   # macOS/Linux
   source chatbot_env/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   # Copy the example file
   cp env.example .env
   
   # Edit .env and add your OpenAI API key
   OPENAI_API_KEY=your_openai_api_key_here
   ```

5. **Run the application**
   ```bash
   python run.py
   ```

6. **Open your browser**
   
   Visit `http://localhost:5000` and start creating chatbots!

## 📖 Usage Guide

### Creating Your First Chatbot

1. **Register an account** on the platform
2. **Click "Create New Chatbot"** and give it a name
3. **Upload training documents** (PDF, DOCX, or TXT files)
4. **Click "Train Chatbot"** and wait for processing to complete
5. **Test your chatbot** using the built-in chat interface
6. **Get the embed code** and add it to your website

### Embedding on Your Website

Simply add this code to your HTML:

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

### Docker Deployment
```dockerfile
# Dockerfile example
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
```

## 💰 Costs

- **OpenAI API**: ~$0.002 per 1,000 tokens (very affordable)
- **Hosting**: Free tier available on most platforms


## 🙏 Acknowledgments

- OpenAI for GPT-3.5 API
- Sentence Transformers for local AI processing
- Flask community for the excellent framework
- Bootstrap for the UI components
