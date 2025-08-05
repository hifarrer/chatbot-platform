from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
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

db = SQLAlchemy()
login_manager = LoginManager()

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
    system_prompt = db.Column(db.Text, default="You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge.")
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

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Admin authentication
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "p@ssword333"

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def get_setting(key, default=None):
    """Get a setting value from the database"""
    setting = Settings.query.filter_by(key=key).first()
    return setting.value if setting else default

def set_setting(key, value):
    """Set a setting value in the database"""
    setting = Settings.query.filter_by(key=key).first()
    if setting:
        setting.value = value
        setting.updated_at = datetime.utcnow()
    else:
        setting = Settings(key=key, value=value)
        db.session.add(setting)
    db.session.commit()
    return setting

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
    
    # Handle PostgreSQL URL for Render.com
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///chatbot_platform.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

    # Create upload directory if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('services', exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    
    # Enable CORS for all routes to allow embedded chatbots on external websites
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
    # Initialize services
    document_processor = DocumentProcessor()
    chatbot_trainer = ChatbotTrainer()

    # Initialize chat service lazily to avoid startup errors
    chat_service = None

    def get_chat_service():
        nonlocal chat_service
        if chat_service is None:
            try:
                chat_service = ChatServiceOpenAI()
            except ValueError as e:
                print(f"⚠️ WARNING: {e}")
                print("💡 OpenAI service not available. Some features may be limited.")
                return None
        return chat_service

    # Routes
    @app.route('/')
    def index():
        # Get homepage chatbot settings
        homepage_chatbot_id = get_setting('homepage_chatbot_id')
        homepage_chatbot_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        homepage_chatbot_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get the chatbot details if configured
        homepage_chatbot = None
        if homepage_chatbot_id:
            homepage_chatbot = Chatbot.query.get(homepage_chatbot_id)
        
        # Fallback to demo chatbot if no specific one is configured
        if not homepage_chatbot:
            homepage_chatbot = Chatbot.query.filter_by(embed_code='a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb').first()
        
        return render_template('index.html',
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/health')
    def health_check():
        """Health check endpoint for Railway"""
        try:
            # Check database connection
            from sqlalchemy import text
            db.session.execute(text('SELECT 1'))
            db_status = "connected"
        except Exception as e:
            print(f"Database health check failed: {e}")
            db_status = "error"
        
        health_data = {
            'status': 'healthy',
            'service': 'ChatBot Platform',
            'database': db_status,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(health_data), 200

    @app.route('/contact')
    def contact():
        return render_template('contact.html')

    @app.route('/plans')
    def plans():
        return render_template('plans.html')

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
            system_prompt = request.form.get('system_prompt', '').strip()
            
            # Use default prompt if none provided
            if not system_prompt:
                system_prompt = "You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge."
            
            chatbot = Chatbot(
                name=name,
                description=description,
                system_prompt=system_prompt,
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

    @app.route('/chatbot/<int:chatbot_id>/update', methods=['POST'])
    @login_required
    def update_chatbot(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        
        description = request.form.get('description', '').strip()
        system_prompt = request.form.get('system_prompt', '').strip()
        
        # Update fields
        chatbot.description = description if description else None
        if system_prompt:
            chatbot.system_prompt = system_prompt
        else:
            chatbot.system_prompt = "You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge."
        
        db.session.commit()
        flash('Chatbot updated successfully!')
        
        return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))

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
            # Process all documents for this chatbot
            all_text = ""
            for doc in documents:
                text = document_processor.process_document(doc.file_path)
                all_text += f"\n\n{text}"
                doc.processed = True
            
            # Train the chatbot
            chatbot_trainer.train_chatbot(chatbot_id, all_text)
            chatbot.is_trained = True
            db.session.commit()
            
            flash('Chatbot trained successfully!')
        except Exception as e:
            flash(f'Training failed: {str(e)}')
        
        return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))

    @app.route('/delete_chatbot/<int:chatbot_id>', methods=['POST'])
    @login_required
    def delete_chatbot(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        
        # Delete associated files
        for document in chatbot.documents:
            try:
                if os.path.exists(document.file_path):
                    os.remove(document.file_path)
            except Exception as e:
                print(f"Error deleting file {document.file_path}: {e}")
        
        # Delete chatbot training data
        try:
            chatbot_trainer.delete_chatbot_data(chatbot_id)
        except Exception as e:
            print(f"Error deleting training data: {e}")
        
        db.session.delete(chatbot)
        db.session.commit()
        
        flash('Chatbot deleted successfully!')
        return redirect(url_for('dashboard'))

    @app.route('/api/chat/<embed_code>', methods=['POST'])
    def chat_api(embed_code):
        try:
            chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
            if not chatbot:
                return jsonify({'error': 'Chatbot not found. Please check the embed code.'}), 404
            
            # Allow chatbots with custom prompts to work even without training
            if not chatbot.is_trained and not chatbot.system_prompt:
                return jsonify({'error': 'Chatbot is not trained yet. Please upload documents and train the chatbot first, or set a system prompt.'}), 400
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data received'}), 400
                
            user_message = data.get('message', '').strip()
            
            if not user_message:
                return jsonify({'error': 'Message is required'}), 400
            
            print(f"🤖 Chat API: Processing message for chatbot {chatbot.id}: '{user_message}'")
            
            # Import and use the ChatService for better response handling
            try:
                from services.chat_service import ChatService
                print(f"✅ Successfully imported ChatService")
                chat_service = ChatService()
                print(f"✅ Successfully created ChatService instance")
            except Exception as e:
                print(f"❌ Failed to import/create ChatService: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': f'Service initialization failed: {str(e)}'}), 500
            
            # Try to use OpenAI service first, fallback to local chat service
            openai_service = get_chat_service()
            if openai_service and hasattr(openai_service, 'get_response'):
                try:
                    print(f"🔄 Trying OpenAI service")
                    response = openai_service.get_response(chatbot.id, user_message)
                    print(f"✅ OpenAI response generated")
                except Exception as e:
                    print(f"⚠️ OpenAI service failed: {e}, falling back to local chat service")
                    try:
                        response = chat_service.get_response(chatbot.id, user_message)
                        print(f"✅ Local chat service response generated")
                    except Exception as e2:
                        print(f"❌ Local chat service also failed: {e2}")
                        return jsonify({'error': f'Both services failed. OpenAI: {str(e)}, Local: {str(e2)}'}), 500
            else:
                # Use local chat service (better than direct trainer)
                print(f"🔄 Using local chat service")
                try:
                    response = chat_service.get_response(chatbot.id, user_message)
                    print(f"✅ Local chat service response generated")
                except Exception as e:
                    print(f"❌ Local chat service failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return jsonify({'error': f'Chat service failed: {str(e)}'}), 500
            
            # Ensure response is not None or empty
            if not response or response.strip() == "":
                response = "I'm sorry, I couldn't generate a proper response. Please try asking your question differently."
            
            # Save conversation
            conversation = Conversation(
                chatbot_id=chatbot.id,
                user_message=user_message,
                bot_response=response
            )
            db.session.add(conversation)
            db.session.commit()
            
            print(f"💬 Response: {response[:100]}...")
            return jsonify({'response': response})
            
        except Exception as e:
            print(f"❌ Chat API Error: {str(e)}")
            print(f"❌ Error type: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            
            # More detailed error information
            error_details = {
                'error': 'Sorry, I encountered an error. Please try again.',
                'debug_info': str(e) if app.debug else None
            }
            
            return jsonify(error_details), 500

    @app.route('/embed/<embed_code>')
    def embed_code(embed_code):
        return render_template('embed.html', embed_code=embed_code)

    @app.route('/test-embed')
    def test_embed():
        # Get the first available chatbot for testing
        chatbot = Chatbot.query.first()
        if chatbot:
            return render_template('embed.html', embed_code=chatbot.embed_code)
        return "No chatbots available for testing"
    
    @app.route('/create-demo-chatbot')
    def create_demo_route():
        """Manual route to create/recreate the demo chatbot"""
        try:
            demo_chatbot = create_demo_chatbot_internal()
            return jsonify({
                'success': True,
                'message': 'Demo chatbot created/updated successfully',
                'embed_code': demo_chatbot.embed_code,
                'is_trained': demo_chatbot.is_trained
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/debug-chat-service')
    def debug_chat_service():
        """Debug endpoint to check chat service functionality"""
        try:
            from services.chat_service import ChatService
            from services.chatbot_trainer import ChatbotTrainer
            
            # Test imports
            chat_service = ChatService()
            trainer = ChatbotTrainer()
            
            # Check methods
            trainer_methods = [method for method in dir(trainer) if not method.startswith('_')]
            chat_service_methods = [method for method in dir(chat_service) if not method.startswith('_')]
            
            return jsonify({
                'success': True,
                'chatbot_trainer_methods': trainer_methods,
                'chat_service_methods': chat_service_methods,
                'trainer_has_generate_response': hasattr(trainer, 'generate_response'),
                'chat_service_has_get_response': hasattr(chat_service, 'get_response')
            })
        except Exception as e:
            import traceback
            return jsonify({
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }), 500

    # Admin Routes
    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                session['admin_logged_in'] = True
                flash('Admin login successful!')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid admin credentials')
        
        return render_template('admin/login.html')

    @app.route('/admin/logout')
    @admin_required
    def admin_logout():
        session.pop('admin_logged_in', None)
        flash('Admin logged out successfully')
        return redirect(url_for('index'))

    @app.route('/admin')
    @admin_required
    def admin_dashboard():
        # Get statistics
        total_users = User.query.count()
        total_chatbots = Chatbot.query.count()
        trained_chatbots = Chatbot.query.filter_by(is_trained=True).count()
        total_conversations = Conversation.query.count()
        
        # Get recent activity
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
        recent_chatbots = Chatbot.query.order_by(Chatbot.created_at.desc()).limit(5).all()
        recent_conversations = Conversation.query.order_by(Conversation.timestamp.desc()).limit(10).all()
        
        return render_template('admin/dashboard.html', 
                             total_users=total_users,
                             total_chatbots=total_chatbots,
                             trained_chatbots=trained_chatbots,
                             total_conversations=total_conversations,
                             recent_users=recent_users,
                             recent_chatbots=recent_chatbots,
                             recent_conversations=recent_conversations)

    @app.route('/admin/users')
    @admin_required
    def admin_users():
        page = request.args.get('page', 1, type=int)
        users = User.query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False)
        return render_template('admin/users.html', users=users)

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_user(user_id):
        user = User.query.get_or_404(user_id)
        
        # Delete user's chatbots and associated data
        for chatbot in user.chatbots:
            # Delete associated files
            for document in chatbot.documents:
                try:
                    if os.path.exists(document.file_path):
                        os.remove(document.file_path)
                except Exception as e:
                    print(f"Error deleting file {document.file_path}: {e}")
            
            # Delete chatbot training data
            try:
                chatbot_trainer.delete_chatbot_data(chatbot.id)
            except Exception as e:
                print(f"Error deleting training data: {e}")
        
        db.session.delete(user)
        db.session.commit()
        
        flash(f'User {user.username} and all associated data deleted successfully!')
        return redirect(url_for('admin_users'))

    @app.route('/admin/chatbots')
    @admin_required
    def admin_chatbots():
        page = request.args.get('page', 1, type=int)
        chatbots = Chatbot.query.order_by(Chatbot.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False)
        return render_template('admin/chatbots.html', chatbots=chatbots)

    @app.route('/admin/chatbots/<int:chatbot_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_chatbot(chatbot_id):
        chatbot = Chatbot.query.get_or_404(chatbot_id)
        
        # Delete associated files
        for document in chatbot.documents:
            try:
                if os.path.exists(document.file_path):
                    os.remove(document.file_path)
            except Exception as e:
                print(f"Error deleting file {document.file_path}: {e}")
        
        # Delete chatbot training data
        try:
            chatbot_trainer.delete_chatbot_data(chatbot_id)
        except Exception as e:
            print(f"Error deleting training data: {e}")
        
        db.session.delete(chatbot)
        db.session.commit()
        
        flash(f'Chatbot {chatbot.name} deleted successfully!')
        return redirect(url_for('admin_chatbots'))

    @app.route('/admin/settings', methods=['GET', 'POST'])
    @admin_required
    def admin_settings():
        if request.method == 'POST':
            # Update homepage chatbot settings
            homepage_chatbot_id = request.form.get('homepage_chatbot_id')
            homepage_chatbot_title = request.form.get('homepage_chatbot_title', 'Platform Assistant')
            homepage_chatbot_placeholder = request.form.get('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
            
            # Save settings
            set_setting('homepage_chatbot_id', homepage_chatbot_id)
            set_setting('homepage_chatbot_title', homepage_chatbot_title)
            set_setting('homepage_chatbot_placeholder', homepage_chatbot_placeholder)
            
            flash('Settings updated successfully!')
            return redirect(url_for('admin_settings'))
        
        # Get current settings
        current_chatbot_id = get_setting('homepage_chatbot_id')
        current_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        current_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get all trained chatbots for selection
        trained_chatbots = Chatbot.query.filter_by(is_trained=True).all()
        
        return render_template('admin/settings.html',
                             current_chatbot_id=current_chatbot_id,
                             current_title=current_title,
                             current_placeholder=current_placeholder,
                             trained_chatbots=trained_chatbots)

    def allowed_file(filename):
        ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    def create_demo_chatbot_internal():
        """Create a demo chatbot for the homepage if it doesn't exist"""
        demo_embed_code = 'a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb'
        
        # Check if demo chatbot already exists
        existing_chatbot = Chatbot.query.filter_by(embed_code=demo_embed_code).first()
        if existing_chatbot and existing_chatbot.is_trained:
            print(f"✅ Demo chatbot already exists and is trained: {demo_embed_code}")
            return existing_chatbot
        
        # Create demo user if doesn't exist
        demo_user = User.query.filter_by(username='demo').first()
        if not demo_user:
            demo_user = User(
                username='demo',
                email='demo@chatbot-platform.com',
                password_hash=generate_password_hash('demo123')
            )
            db.session.add(demo_user)
            db.session.commit()
        
        # Create or update demo chatbot
        if existing_chatbot:
            demo_chatbot = existing_chatbot
            # Update system prompt if it's the default
            if not demo_chatbot.system_prompt or demo_chatbot.system_prompt == "You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge.":
                demo_chatbot.system_prompt = "You are the Platform Assistant for the ChatBot Platform. You are knowledgeable, friendly, and enthusiastic about helping users understand how to create and deploy AI chatbots. You help users with questions about features, setup, training, and deployment. Be encouraging and provide clear, actionable guidance."
                db.session.commit()
        else:
            demo_chatbot = Chatbot(
                name='Platform Assistant',
                description='A helpful assistant that can answer questions about the chatbot platform',
                system_prompt='You are the Platform Assistant for the ChatBot Platform. You are knowledgeable, friendly, and enthusiastic about helping users understand how to create and deploy AI chatbots. You help users with questions about features, setup, training, and deployment. Be encouraging and provide clear, actionable guidance.',
                embed_code=demo_embed_code,
                user_id=demo_user.id,
                is_trained=False
            )
            db.session.add(demo_chatbot)
            db.session.commit()
        
        # Create demo training data
        demo_content = """
About the Chatbot Platform

This is a comprehensive AI-powered chatbot platform that enables businesses and individuals to create intelligent conversational assistants for their websites. Our platform combines ease of use with powerful AI technology to deliver professional chatbot solutions.

Core Services Offered

Document-Based Training: Upload PDF, DOCX, and TXT files to train your chatbot with your specific content. The platform extracts text from documents and creates intelligent responses based on your material.

Multi-Bot Management: Create unlimited chatbots for different purposes - customer support, FAQ assistance, product information, or specialized knowledge bases.

Easy Website Integration: Get a simple embed code that can be added to any website in minutes. No technical expertise required.

AI-Powered Responses: Uses advanced natural language processing with fallback to OpenAI integration for enhanced conversational abilities.

Real-Time Chat Interface: Professional chat widget with typing indicators, customizable themes, and mobile-responsive design.

Conversation Analytics: Track all conversations, monitor chatbot performance, and analyze user interactions through your dashboard.

How to Get Started

Step 1: Create Your Account
Register for a free account using your email address. No credit card required to start building chatbots.

Step 2: Create Your First Chatbot
From your dashboard, click "Create Chatbot" and give it a name and description that reflects its purpose.

Step 3: Upload Training Documents
Upload relevant documents (manuals, FAQs, product information, policies) in PDF, DOCX, or TXT format. The platform will process these automatically.

Step 4: Train Your Chatbot
Click the "Train" button to process your documents and create the AI knowledge base. This usually takes just a few minutes.

Step 5: Get Your Embed Code
Once trained, copy the provided embed code and paste it into your website's HTML. The chatbot will appear as a floating widget.

Usage Examples

Customer Support: Upload your support documentation, product manuals, and FAQ documents to create a 24/7 customer service assistant.

Educational Content: Teachers can upload course materials, syllabi, and reading lists to create study assistants for students.

Business Information: Real estate agents can upload property details, market reports, and service information to help potential clients.

Technical Documentation: Software companies can upload API documentation, user guides, and troubleshooting materials.

Company Policies: HR departments can create chatbots trained on employee handbooks, benefits information, and company policies.

Platform Features

Drag-and-Drop File Upload: Simple interface for uploading multiple documents at once.

Automatic Text Extraction: Intelligent processing of PDF and DOCX files to extract relevant text content.

Smart Response Generation: AI algorithms that understand context and provide relevant answers from your training materials.

Conversation History: Complete logs of all chatbot interactions for analysis and improvement.

Multiple Deployment Options: Embed codes work on WordPress, Shopify, custom websites, and any HTML-based platform.

Mobile Optimization: Chatbot widgets automatically adapt to mobile devices for seamless user experience.

Customization Options: Adjust colors, positioning, welcome messages, and placeholder text to match your brand.

Technical Specifications

Supported File Formats: PDF (including scanned documents with OCR), Microsoft Word DOCX, and plain text TXT files.

File Size Limits: Up to 16MB per file upload with support for multiple files per chatbot.

Response Time: Typically under 2 seconds for generating responses from trained content.

Deployment: Cloud-hosted solution with 99.9% uptime and automatic scaling.

Security: All data is encrypted in transit and at rest, with secure API endpoints for chat functionality.

Integration: RESTful API available for custom integrations and advanced use cases.

Pricing and Plans

Free Tier: Create unlimited chatbots, upload documents, and embed on websites at no cost.

OpenAI Integration: Optional upgrade for enhanced AI responses using GPT technology (requires OpenAI API key).

Enterprise Features: Contact us for advanced analytics, custom branding, and priority support options.

Support and Resources

Documentation: Comprehensive guides available for setup, customization, and troubleshooting.

Community: Access to user forums and knowledge sharing with other platform users.

Contact Support: Direct support available through the contact form for technical assistance.

Regular Updates: Platform continuously improved with new features and AI enhancements.

Getting Help

If you need assistance, you can:
- Check the documentation and guides in your dashboard
- Contact support through the contact form
- Register for an account to access the full tutorial system
- Use this demo chatbot to ask specific questions about features and functionality

The platform is designed to be user-friendly while providing powerful AI capabilities for creating professional chatbot solutions.
"""
        
        try:
            chatbot_trainer.train_chatbot(demo_chatbot.id, demo_content)
            demo_chatbot.is_trained = True
            db.session.commit()
            print(f"✅ Demo chatbot created and trained with embed code: {demo_embed_code}")
        except Exception as e:
            print(f"⚠️ Demo chatbot created but training failed: {e}")
            import traceback
            traceback.print_exc()
        
        return demo_chatbot

    with app.app_context():
        db.create_all()
        # Create demo chatbot after all services are initialized
        try:
            create_demo_chatbot_internal()
        except Exception as e:
            print(f"⚠️ Failed to create demo chatbot: {e}")
    
    return app 