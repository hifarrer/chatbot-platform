from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import json
import uuid
from datetime import datetime
from services.document_processor import DocumentProcessor
from services.chatbot_trainer import ChatbotTrainer
from services.chat_service_openai import ChatServiceOpenAI

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed, skip loading .env file
    pass

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatbot_platform.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create upload directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/css', exist_ok=True)
os.makedirs('static/js', exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('services', exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize services
document_processor = DocumentProcessor()
chatbot_trainer = ChatbotTrainer()
chat_service = ChatServiceOpenAI()

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    chatbots = db.relationship('Chatbot', backref='owner', lazy=True, cascade='all, delete-orphan')

class Chatbot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    embed_code = db.Column(db.String(36), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_trained = db.Column(db.Boolean, default=False)
    documents = db.relationship('Document', backref='chatbot', lazy=True, cascade='all, delete-orphan')
    conversations = db.relationship('Conversation', backref='chatbot', lazy=True, cascade='all, delete-orphan')

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    chatbot_id = db.Column(db.Integer, db.ForeignKey('chatbot.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chatbot_id = db.Column(db.Integer, db.ForeignKey('chatbot.id'), nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    bot_response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('register'))
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        flash('Registration successful!')
        return redirect(url_for('dashboard'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    chatbots = Chatbot.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', chatbots=chatbots)

@app.route('/create_chatbot', methods=['GET', 'POST'])
@login_required
def create_chatbot():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        
        chatbot = Chatbot(
            name=name,
            description=description,
            embed_code=str(uuid.uuid4()),
            user_id=current_user.id
        )
        
        db.session.add(chatbot)
        db.session.commit()
        
        flash('Chatbot created successfully!')
        return redirect(url_for('chatbot_details', chatbot_id=chatbot.id))
    
    return render_template('create_chatbot.html')

@app.route('/chatbot/<int:chatbot_id>')
@login_required
def chatbot_details(chatbot_id):
    chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
    documents = Document.query.filter_by(chatbot_id=chatbot_id).all()
    conversations = Conversation.query.filter_by(chatbot_id=chatbot_id).order_by(Conversation.timestamp.desc()).limit(50).all()
    
    return render_template('chatbot_details.html', chatbot=chatbot, documents=documents, conversations=conversations)

@app.route('/upload_document/<int:chatbot_id>', methods=['POST'])
@login_required
def upload_document(chatbot_id):
    chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
    
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        document = Document(
            filename=unique_filename,
            original_filename=filename,
            file_path=file_path,
            chatbot_id=chatbot_id
        )
        
        db.session.add(document)
        db.session.commit()
        
        flash('Document uploaded successfully!')
    else:
        flash('Invalid file type. Please upload PDF, DOCX, or TXT files.')
    
    return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))

@app.route('/train_chatbot/<int:chatbot_id>', methods=['POST'])
@login_required
def train_chatbot(chatbot_id):
    chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
    documents = Document.query.filter_by(chatbot_id=chatbot_id).all()
    
    if not documents:
        flash('Please upload at least one document before training.')
        return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
    
    try:
        # Process documents and train chatbot
        all_text = ""
        for doc in documents:
            text = document_processor.process_document(doc.file_path)
            all_text += text + "\n\n"
            doc.processed = True
        
        # Train the chatbot with the processed text
        chatbot_trainer.train_chatbot(chatbot_id, all_text)
        
        chatbot.is_trained = True
        db.session.commit()
        
        flash('Chatbot trained successfully!')
    except Exception as e:
        flash(f'Error training chatbot: {str(e)}')
    
    return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))

@app.route('/delete_chatbot/<int:chatbot_id>', methods=['POST'])
@login_required
def delete_chatbot(chatbot_id):
    chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
    
    # Delete associated files
    for doc in chatbot.documents:
        if os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    
    # Delete chatbot training data
    chatbot_trainer.delete_chatbot_data(chatbot_id)
    
    db.session.delete(chatbot)
    db.session.commit()
    
    flash('Chatbot deleted successfully!')
    return redirect(url_for('dashboard'))

# API Routes for embedded chatbot
@app.route('/api/chat/<embed_code>', methods=['POST'])
def chat_api(embed_code):
    chatbot = Chatbot.query.filter_by(embed_code=embed_code).first_or_404()
    
    if not chatbot.is_trained:
        return jsonify({'error': 'Chatbot is not trained yet'}), 400
    
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({'error': 'Message is required'}), 400
    
    user_message = data['message']
    
    try:
        bot_response = chat_service.get_response(chatbot.id, user_message)
        
        # Save conversation
        conversation = Conversation(
            chatbot_id=chatbot.id,
            user_message=user_message,
            bot_response=bot_response
        )
        db.session.add(conversation)
        db.session.commit()
        
        return jsonify({'response': bot_response})
    except Exception as e:
        return jsonify({'error': 'Failed to generate response'}), 500

@app.route('/embed/<embed_code>')
def embed_code(embed_code):
    return render_template('embed.html', embed_code=embed_code)

@app.route('/test-embed')
def test_embed():
    """Serve the test embed page"""
    try:
        with open('test_embed.html', 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return "Test embed page not found. Please make sure test_embed.html exists in the root directory.", 404

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True) 