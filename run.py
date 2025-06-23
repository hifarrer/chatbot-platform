#!/usr/bin/env python3
"""
Application entry point for the Chatbot Platform
"""
import os
import sys
import subprocess
import importlib.util
from app import create_app

def check_dependencies():
    """Check if critical dependencies are available"""
    try:
        import flask
        import flask_sqlalchemy
        print("✅ Core dependencies available")
        return True
    except ImportError as e:
        print(f"❌ Missing critical dependency: {e}")
        return False

def initialize_app():
    """Initialize the application with required directories"""
    directories = ['uploads', 'training_data', 'instance']
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"Created directory: {directory}")

if __name__ == '__main__':
    print("Starting Chatbot Platform...")
    
    try:
        # Check dependencies
        if not check_dependencies():
            sys.exit(1)
        
        # Initialize app
        initialize_app()
        
        # Create Flask app
        app = create_app()
        
        # Get port from environment or default to 5000
        port = int(os.environ.get('PORT', 5000))
        
        # Run the app
        print(f"Starting server on port {port}...")
        print(f"Health check available at: http://0.0.0.0:{port}/health")
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        print(f"Failed to start application: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
else:
    # For production deployment (gunicorn)
    print("Creating app for production...")
    try:
        initialize_app()
        app = create_app()
        print("App created successfully for gunicorn")
    except Exception as e:
        print(f"Failed to create app: {e}")
        import traceback
        traceback.print_exc()
        raise 