@echo off
echo 🤖 ChatBot Platform Setup for Windows
echo =====================================

echo.
echo 📝 Step 1: Creating virtual environment...
python -m venv chatbot_env

echo.
echo 📝 Step 2: Activating virtual environment...
call chatbot_env\Scripts\activate.bat

echo.
echo 📝 Step 3: Upgrading pip...
python -m pip install --upgrade pip

echo.
echo 📝 Step 4: Installing basic dependencies...
pip install -r requirements-minimal.txt

echo.
echo 📝 Step 5: Installing AI packages (this may take a while)...
pip install sentence-transformers scikit-learn numpy

echo.
echo ✅ Setup complete! 
echo.
echo 🚀 To start the application:
echo    1. Run: chatbot_env\Scripts\activate.bat
echo    2. Run: python run.py
echo    3. Open: http://localhost:5000
echo.
pause 