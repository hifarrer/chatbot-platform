#!/usr/bin/env python3
"""
ChatBot Platform Runner

This script provides an easy way to run the ChatBot Platform with proper initialization.
"""

import os
import sys
from app import app, db

def check_dependencies():
    """Check if all required dependencies are installed."""
    try:
        import flask
        import flask_sqlalchemy
        import flask_login
        import sentence_transformers
        import numpy
        import sklearn
        print("✅ All dependencies are installed!")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def create_directories():
    """Create necessary directories if they don't exist."""
    directories = ['uploads', 'training_data', 'static/css', 'static/js', 'templates']
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            print(f"📁 Created directory: {directory}")

def initialize_database():
    """Initialize the database if it doesn't exist."""
    with app.app_context():
        db.create_all()
        print("📚 Database initialized!")

def main():
    """Main function to run the application."""
    print("🤖 ChatBot Platform - Starting up...")
    print("=" * 50)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Create directories
    create_directories()
    
    # Initialize database
    initialize_database()
    
    print("=" * 50)
    print("🚀 Starting ChatBot Platform...")
    print("📍 URL: http://localhost:5000")
    print("⭐ Features:")
    print("   - User registration and login")
    print("   - Create and manage chatbots")
    print("   - Upload documents for training")
    print("   - Get embed codes for websites")
    print("=" * 50)
    print("📖 Check README.md for detailed instructions")
    print("🛑 Press Ctrl+C to stop the server")
    print("=" * 50)
    
    # Run the application
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n👋 ChatBot Platform stopped. Goodbye!")
    except Exception as e:
        print(f"❌ Error starting application: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main() 