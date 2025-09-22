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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
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

class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    monthly_price = db.Column(db.Float, nullable=False, default=0.0)
    yearly_price = db.Column(db.Float, nullable=False, default=0.0)
    stripe_monthly_price_id = db.Column(db.String(255))
    stripe_yearly_price_id = db.Column(db.String(255))
    chatbot_limit = db.Column(db.Integer, nullable=False, default=1)
    features = db.Column(db.Text)  # JSON string of features
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SMTPSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    smtp_server = db.Column(db.String(255), nullable=False)
    smtp_port = db.Column(db.Integer, nullable=False, default=587)
    smtp_username = db.Column(db.String(255), nullable=False)
    smtp_password = db.Column(db.String(255), nullable=False)
    smtp_use_tls = db.Column(db.Boolean, default=True, nullable=False)
    smtp_use_ssl = db.Column(db.Boolean, default=False, nullable=False)
    from_email = db.Column(db.String(255), nullable=False)
    from_name = db.Column(db.String(255), nullable=False)
    admin_email = db.Column(db.String(255), nullable=False)  # Where contact form emails are sent
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_user_plan(user):
    """Get the user's current plan. For now, return the Free plan as default."""
    # TODO: Implement user subscription logic when payment system is added
    # For now, all users get the Free plan
    free_plan = Plan.query.filter_by(name='Free', is_active=True).first()
    if not free_plan:
        # Fallback: create a default free plan if none exists
        free_plan = Plan(
            name='Free',
            description='Free plan for all users',
            monthly_price=0.0,
            yearly_price=0.0,
            chatbot_limit=3,
            features=json.dumps(['Up to 3 chatbots', 'Basic support']),
            is_active=True
        )
        db.session.add(free_plan)
        db.session.commit()
    return free_plan

def get_smtp_settings():
    """Get the active SMTP settings from the database."""
    return SMTPSettings.query.filter_by(is_active=True).first()

def send_email(to_email, subject, body, is_html=False):
    """Send an email using the configured SMTP settings."""
    smtp_settings = get_smtp_settings()
    if not smtp_settings:
        raise Exception("No SMTP settings configured")
    
    # Create message
    msg = MIMEMultipart('alternative')
    msg['From'] = f"{smtp_settings.from_name} <{smtp_settings.from_email}>"
    msg['To'] = to_email
    msg['Subject'] = subject
    
    # Add body
    if is_html:
        msg.attach(MIMEText(body, 'html'))
    else:
        msg.attach(MIMEText(body, 'plain'))
    
    # Connect to server and send email
    try:
        if smtp_settings.smtp_use_ssl:
            server = smtplib.SMTP_SSL(smtp_settings.smtp_server, smtp_settings.smtp_port)
        else:
            server = smtplib.SMTP(smtp_settings.smtp_server, smtp_settings.smtp_port)
            if smtp_settings.smtp_use_tls:
                server.starttls()
        
        server.login(smtp_settings.smtp_username, smtp_settings.smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        raise Exception(f"Failed to send email: {str(e)}")

# Admin authentication
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
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
    
    # Add custom Jinja2 filter for JSON parsing
    @app.template_filter('from_json')
    def from_json_filter(json_string):
        try:
            return json.loads(json_string)
        except:
            return []
    
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

    @app.route('/contact', methods=['GET', 'POST'])
    def contact():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            subject = request.form.get('subject', '').strip()
            message = request.form.get('message', '').strip()
            
            # Basic validation
            if not name or not email or not subject or not message:
                flash('All fields are required.', 'error')
                return render_template('contact.html')
            
            # Email validation
            if '@' not in email or '.' not in email:
                flash('Please enter a valid email address.', 'error')
                return render_template('contact.html')
            
            try:
                # Get SMTP settings
                smtp_settings = get_smtp_settings()
                if not smtp_settings:
                    flash('Email service is not configured. Please contact the administrator.', 'error')
                    return render_template('contact.html')
                
                # Create email content
                email_subject = f"Contact Form: {subject}"
                email_body = f"""
New contact form submission from {name} ({email})

Subject: {subject}

Message:
{message}

---
Sent from Chatbot Platform Contact Form
Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
                """
                
                # Send email to admin
                send_email(smtp_settings.admin_email, email_subject, email_body)
                
                # Send confirmation email to user
                confirmation_subject = "Thank you for contacting us"
                confirmation_body = f"""
Dear {name},

Thank you for contacting us. We have received your message and will get back to you as soon as possible.

Your message:
Subject: {subject}
Message: {message}

Best regards,
{smtp_settings.from_name}
                """
                
                send_email(email, confirmation_subject, confirmation_body)
                
                flash('Thank you for your message! We will get back to you soon.', 'success')
                return redirect(url_for('contact'))
                
            except Exception as e:
                flash(f'Failed to send message. Please try again later. Error: {str(e)}', 'error')
                return render_template('contact.html')
        
        return render_template('contact.html')

    @app.route('/plans')
    def plans():
        plans = Plan.query.filter_by(is_active=True).order_by(Plan.monthly_price.asc()).all()
        return render_template('plans.html', plans=plans)

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
        user_plan = get_user_plan(current_user)
        current_chatbot_count = len(chatbots)
        remaining_chatbots = user_plan.chatbot_limit - current_chatbot_count
        
        return render_template('dashboard.html', 
                             chatbots=chatbots,
                             user_plan=user_plan,
                             current_chatbot_count=current_chatbot_count,
                             remaining_chatbots=remaining_chatbots)

    @app.route('/create_chatbot', methods=['GET', 'POST'])
    @login_required
    def create_chatbot():
        if request.method == 'POST':
            # Check chatbot limit for user's plan
            user_plan = get_user_plan(current_user)
            current_chatbot_count = Chatbot.query.filter_by(user_id=current_user.id).count()
            
            if current_chatbot_count >= user_plan.chatbot_limit:
                flash(f'You have reached your plan limit of {user_plan.chatbot_limit} chatbots. Please upgrade your plan to create more chatbots.', 'warning')
                return redirect(url_for('create_chatbot'))
            
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
        
        # Get user's plan info for display
        user_plan = get_user_plan(current_user)
        current_chatbot_count = Chatbot.query.filter_by(user_id=current_user.id).count()
        remaining_chatbots = user_plan.chatbot_limit - current_chatbot_count
        
        return render_template('create_chatbot.html', 
                             user_plan=user_plan, 
                             current_chatbot_count=current_chatbot_count,
                             remaining_chatbots=remaining_chatbots)

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
            
            user = User.query.filter_by(username=username).first()
            
            if user and user.is_admin and check_password_hash(user.password_hash, password):
                login_user(user)
                flash('Admin login successful!')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid admin credentials')
        
        return render_template('admin/login.html')

    @app.route('/admin/logout')
    @admin_required
    def admin_logout():
        logout_user()
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

    @app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_edit_user(user_id):
        user = User.query.get_or_404(user_id)
        
        if request.method == 'POST':
            # Update user information
            user.username = request.form['username']
            user.email = request.form['email']
            
            # Handle password update (only if provided)
            new_password = request.form.get('password', '').strip()
            if new_password:
                user.password_hash = generate_password_hash(new_password)
            
            # Handle admin status
            user.is_admin = 'is_admin' in request.form
            
            # Check for username/email conflicts
            existing_user = User.query.filter(
                User.username == user.username,
                User.id != user.id
            ).first()
            if existing_user:
                flash('Username already exists!')
                return render_template('admin/edit_user.html', user=user)
            
            existing_email = User.query.filter(
                User.email == user.email,
                User.id != user.id
            ).first()
            if existing_email:
                flash('Email already exists!')
                return render_template('admin/edit_user.html', user=user)
            
            db.session.commit()
            flash(f'User {user.username} updated successfully!')
            return redirect(url_for('admin_users'))
        
        return render_template('admin/edit_user.html', user=user)

    @app.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
    @admin_required
    def admin_toggle_user_admin(user_id):
        user = User.query.get_or_404(user_id)
        
        # Prevent admin from demoting themselves
        if user.id == current_user.id:
            flash('You cannot change your own admin status!')
            return redirect(url_for('admin_users'))
        
        # Toggle admin status
        user.is_admin = not user.is_admin
        db.session.commit()
        
        status = "promoted to admin" if user.is_admin else "demoted from admin"
        flash(f'User {user.username} has been {status}!')
        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_user(user_id):
        user = User.query.get_or_404(user_id)
        
        # Prevent admin from deleting themselves
        if user.id == current_user.id:
            flash('You cannot delete your own account!')
            return redirect(url_for('admin_users'))
        
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

    @app.route('/admin/plans')
    @admin_required
    def admin_plans():
        page = request.args.get('page', 1, type=int)
        plans = Plan.query.order_by(Plan.monthly_price.asc()).paginate(
            page=page, per_page=20, error_out=False)
        return render_template('admin/plans.html', plans=plans)

    @app.route('/admin/plans/create', methods=['GET', 'POST'])
    @admin_required
    def admin_create_plan():
        if request.method == 'POST':
            name = request.form['name']
            description = request.form['description']
            monthly_price = float(request.form['monthly_price'])
            yearly_price = float(request.form['yearly_price'])
            chatbot_limit = int(request.form['chatbot_limit'])
            stripe_monthly_price_id = request.form.get('stripe_monthly_price_id', '').strip()
            stripe_yearly_price_id = request.form.get('stripe_yearly_price_id', '').strip()
            features_text = request.form.get('features', '')
            is_active = 'is_active' in request.form
            
            # Convert features text to JSON
            features_list = [feature.strip() for feature in features_text.split('\n') if feature.strip()]
            features_json = json.dumps(features_list)
            
            plan = Plan(
                name=name,
                description=description,
                monthly_price=monthly_price,
                yearly_price=yearly_price,
                chatbot_limit=chatbot_limit,
                stripe_monthly_price_id=stripe_monthly_price_id if stripe_monthly_price_id else None,
                stripe_yearly_price_id=stripe_yearly_price_id if stripe_yearly_price_id else None,
                features=features_json,
                is_active=is_active
            )
            
            db.session.add(plan)
            db.session.commit()
            
            flash(f'Plan "{name}" created successfully!')
            return redirect(url_for('admin_plans'))
        
        return render_template('admin/create_plan.html')

    @app.route('/admin/plans/<int:plan_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_edit_plan(plan_id):
        plan = Plan.query.get_or_404(plan_id)
        
        if request.method == 'POST':
            plan.name = request.form['name']
            plan.description = request.form['description']
            plan.monthly_price = float(request.form['monthly_price'])
            plan.yearly_price = float(request.form['yearly_price'])
            plan.chatbot_limit = int(request.form['chatbot_limit'])
            plan.stripe_monthly_price_id = request.form.get('stripe_monthly_price_id', '').strip()
            plan.stripe_yearly_price_id = request.form.get('stripe_yearly_price_id', '').strip()
            features_text = request.form.get('features', '')
            plan.is_active = 'is_active' in request.form
            
            # Convert features text to JSON
            features_list = [feature.strip() for feature in features_text.split('\n') if feature.strip()]
            plan.features = json.dumps(features_list)
            
            # Check for name conflicts
            existing_plan = Plan.query.filter(
                Plan.name == plan.name,
                Plan.id != plan.id
            ).first()
            if existing_plan:
                flash('Plan name already exists!')
                return render_template('admin/edit_plan.html', plan=plan)
            
            db.session.commit()
            flash(f'Plan "{plan.name}" updated successfully!')
            return redirect(url_for('admin_plans'))
        
        return render_template('admin/edit_plan.html', plan=plan)

    @app.route('/admin/plans/<int:plan_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_plan(plan_id):
        plan = Plan.query.get_or_404(plan_id)
        
        db.session.delete(plan)
        db.session.commit()
        
        flash(f'Plan "{plan.name}" deleted successfully!')
        return redirect(url_for('admin_plans'))

    @app.route('/admin/smtp-settings', methods=['GET', 'POST'])
    @admin_required
    def admin_smtp_settings():
        if request.method == 'POST':
            smtp_server = request.form['smtp_server']
            smtp_port = int(request.form['smtp_port'])
            smtp_username = request.form['smtp_username']
            smtp_password = request.form['smtp_password']
            smtp_use_tls = 'smtp_use_tls' in request.form
            smtp_use_ssl = 'smtp_use_ssl' in request.form
            from_email = request.form['from_email']
            from_name = request.form['from_name']
            admin_email = request.form['admin_email']
            
            # Get existing SMTP settings or create new
            smtp_settings = SMTPSettings.query.filter_by(is_active=True).first()
            if not smtp_settings:
                smtp_settings = SMTPSettings()
                db.session.add(smtp_settings)
            
            # Update settings
            smtp_settings.smtp_server = smtp_server
            smtp_settings.smtp_port = smtp_port
            smtp_settings.smtp_username = smtp_username
            smtp_settings.smtp_password = smtp_password
            smtp_settings.smtp_use_tls = smtp_use_tls
            smtp_settings.smtp_use_ssl = smtp_use_ssl
            smtp_settings.from_email = from_email
            smtp_settings.from_name = from_name
            smtp_settings.admin_email = admin_email
            smtp_settings.is_active = True
            
            db.session.commit()
            
            flash('SMTP settings updated successfully!')
            return redirect(url_for('admin_smtp_settings'))
        
        # Get current SMTP settings
        smtp_settings = SMTPSettings.query.filter_by(is_active=True).first()
        
        return render_template('admin/smtp_settings.html', smtp_settings=smtp_settings)

    @app.route('/admin/smtp-settings/test', methods=['POST'])
    @admin_required
    def admin_test_smtp():
        try:
            # Get current SMTP settings
            smtp_settings = SMTPSettings.query.filter_by(is_active=True).first()
            if not smtp_settings:
                return jsonify({'success': False, 'message': 'No SMTP settings configured'})
            
            # Send test email to admin email
            test_subject = "SMTP Test Email"
            test_body = f"""
This is a test email from your Chatbot Platform.

SMTP Settings:
- Server: {smtp_settings.smtp_server}
- Port: {smtp_settings.smtp_port}
- Username: {smtp_settings.smtp_username}
- Use TLS: {smtp_settings.smtp_use_tls}
- Use SSL: {smtp_settings.smtp_use_ssl}
- From: {smtp_settings.from_name} <{smtp_settings.from_email}>

If you receive this email, your SMTP settings are working correctly!

Sent at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
            """
            
            send_email(smtp_settings.admin_email, test_subject, test_body)
            return jsonify({'success': True, 'message': 'Test email sent successfully!'})
            
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to send test email: {str(e)}'})

    with app.app_context():
        db.create_all()
        # Create demo chatbot after all services are initialized
        try:
            create_demo_chatbot_internal()
        except Exception as e:
            print(f"⚠️ Failed to create demo chatbot: {e}")
    
    return app 