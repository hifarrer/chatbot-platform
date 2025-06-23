#!/usr/bin/env python3
"""
Railway Environment Test Script
This script tests if the Railway environment is set up correctly
"""

import sys
import os

def test_python_version():
    print(f"Python version: {sys.version}")
    if sys.version_info < (3, 8):
        print("❌ Python version too old")
        return False
    print("✅ Python version OK")
    return True

def test_environment_variables():
    print("\n🔍 Environment Variables:")
    required_vars = ['PORT']
    optional_vars = ['SECRET_KEY', 'OPENAI_API_KEY', 'DATABASE_URL']
    
    for var in required_vars:
        value = os.environ.get(var)
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: Not set")
    
    for var in optional_vars:
        value = os.environ.get(var)
        if value:
            print(f"✅ {var}: {'*' * min(len(value), 10)}... (hidden)")
        else:
            print(f"⚠️  {var}: Not set (optional)")

def test_imports():
    print("\n📦 Testing imports...")
    
    required_imports = [
        ('flask', 'Flask'),
        ('flask_sqlalchemy', 'SQLAlchemy'),
        ('flask_login', 'LoginManager'),
        ('werkzeug.security', 'generate_password_hash'),
        ('PyPDF2', 'PdfReader'),
        ('docx', 'Document'),
        ('openai', 'OpenAI'),
    ]
    
    success_count = 0
    for module, item in required_imports:
        try:
            __import__(module)
            print(f"✅ {module}")
            success_count += 1
        except ImportError as e:
            print(f"❌ {module}: {e}")
    
    print(f"\n📊 Import success: {success_count}/{len(required_imports)}")
    return success_count == len(required_imports)

def test_app_creation():
    print("\n🚀 Testing app creation...")
    try:
        from app import create_app
        app = create_app()
        print("✅ App created successfully")
        
        # Test health endpoint
        with app.test_client() as client:
            response = client.get('/health')
            print(f"✅ Health endpoint: {response.status_code}")
            print(f"   Response: {response.get_json()}")
        
        return True
    except Exception as e:
        print(f"❌ App creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("🧪 Railway Environment Test")
    print("=" * 50)
    
    tests = [
        ("Python Version", test_python_version),
        ("Environment Variables", test_environment_variables),
        ("Package Imports", test_imports),
        ("App Creation", test_app_creation),
    ]
    
    passed = 0
    for test_name, test_func in tests:
        print(f"\n🔬 {test_name}")
        print("-" * 30)
        if test_func():
            passed += 1
    
    print("\n" + "=" * 50)
    print(f"🎯 Tests passed: {passed}/{len(tests)}")
    
    if passed == len(tests):
        print("🎉 All tests passed! Railway should work.")
        return 0
    else:
        print("❌ Some tests failed. Check the errors above.")
        return 1

if __name__ == '__main__':
    sys.exit(main()) 