from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, send_file, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
import json
import uuid
import secrets
import resend
from datetime import datetime, timedelta
from services.document_processor import DocumentProcessor
from services.chatbot_trainer import ChatbotTrainer
from services.chat_service_openai import ChatServiceOpenAI

# Optional Stripe dependency (guarded)
try:
    import stripe  # type: ignore
except Exception:
    stripe = None

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
    # Profile fields
    full_name = db.Column(db.String(100), nullable=True)
    business_name = db.Column(db.String(100), nullable=True)
    website = db.Column(db.String(255), nullable=True)
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
    avatar_filename = db.Column(db.String(255), nullable=True)  # Custom avatar image
    greeting_message = db.Column(db.String(500), nullable=True)  # Custom greeting message
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
    response_status = db.Column(db.String(20), default='active')  # 'active', 'resolved', 'pending'

class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    monthly_price = db.Column(db.Float, nullable=False, default=0.0)
    yearly_price = db.Column(db.Float, nullable=False, default=0.0)
    stripe_monthly_price_id = db.Column(db.String(255))
    stripe_yearly_price_id = db.Column(db.String(255))
    chatbot_limit = db.Column(db.Integer, nullable=False, default=1)
    file_size_limit_mb = db.Column(db.Integer, nullable=False, default=10)  # File size limit in MB
    features = db.Column(db.Text)  # JSON string of features
    is_active = db.Column(db.Boolean, default=True)
    show_contact_sales = db.Column(db.Boolean, default=False)  # Show Contact Sales button instead of Stripe checkout
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), nullable=False, default='active')
    current_period_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='password_reset_tokens')

class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_title = db.Column(db.String(255), nullable=False, default='ChatBot Platform')
    logo_filename = db.Column(db.String(255), nullable=True)  # Keep for backward compatibility
    logo_base64 = db.Column(db.Text, nullable=True)  # Store base64 encoded image
    meta_tags = db.Column(db.Text, nullable=True)  # Comma-separated meta tags
    hero_title = db.Column(db.String(255), nullable=False, default='Build your own AI chatbot')
    hero_subtitle = db.Column(db.Text, nullable=True)
    hero_icon_filename = db.Column(db.String(255), nullable=True)  # Keep for backward compatibility
    hero_icon_base64 = db.Column(db.Text, nullable=True)  # Store base64 encoded hero icon
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class FAQ(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    order = db.Column(db.Integer, default=0, nullable=False)  # For ordering FAQ items
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class HomepageSection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    section_type = db.Column(db.String(50), nullable=False)  # 'how_it_works', 'features', 'stats', 'cta'
    title = db.Column(db.String(255), nullable=True)
    subtitle = db.Column(db.Text, nullable=True)
    content = db.Column(db.Text, nullable=True)  # JSON content for complex sections
    order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_user_plan(user):
    """Get the user's current plan based on active subscription, else Free."""
    try:
        sub = UserSubscription.query.filter_by(user_id=user.id, status='active').order_by(UserSubscription.created_at.desc()).first()
        if sub:
            plan = Plan.query.get(sub.plan_id)
            if plan and plan.is_active:
                return plan
    except Exception:
        pass

    free_plan = Plan.query.filter_by(name='Free', is_active=True).first()
    if not free_plan:
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


def get_site_settings():
    """Get the active site settings from the database."""
    site_settings = SiteSettings.query.filter_by(is_active=True).first()
    if not site_settings:
        # Create default site settings if none exist
        site_settings = SiteSettings(
            site_title='ChatBot Platform',
            meta_tags='chatbot, AI, customer service, automation',
            hero_title='Build your own AI chatbot',
            hero_subtitle='Create intelligent chatbots for your business in minutes'
        )
        db.session.add(site_settings)
        db.session.commit()
    return site_settings

def send_email(to_email, subject, body, is_html=False):
    """Send an email using Resend API."""
    try:
        # Set Resend API key
        resend.api_key = os.getenv('RESEND_API_KEY')
        if not resend.api_key:
            raise Exception("RESEND_API_KEY not configured")
        
        # Get sender information from environment variables
        from_email = os.getenv('RESEND_FROM_EMAIL')
        from_name = os.getenv('RESEND_FROM_NAME', 'ChatBot Platform')
        
        if not from_email:
            raise Exception("RESEND_FROM_EMAIL not configured")
        
        # Prepare email data
        email_data = {
            "from": f"{from_name} <{from_email}>",
            "to": [to_email],
            "subject": subject
        }
        
        # Add content based on type
        if is_html:
            email_data["html"] = body
        else:
            email_data["text"] = body
        
        print(f"DEBUG: Sending email with data: {email_data}")  # Debug log
        
        # Send email using Resend
        response = resend.Emails.send(email_data)
        
        print(f"DEBUG: Resend response: {response}")  # Debug log
        
        if response and (hasattr(response, 'id') or (isinstance(response, dict) and 'id' in response)):
            return True
        else:
            raise Exception(f"Invalid response from Resend: {response}")
            
    except Exception as e:
        print(f"DEBUG: Email error: {str(e)}")  # Debug log
        raise Exception(f"Failed to send email: {str(e)}")

def generate_password_reset_token(user):
    """Generate a password reset token for a user"""
    # Create a secure random token
    token = secrets.token_urlsafe(32)
    
    # Set expiration time (1 hour from now)
    expires_at = datetime.utcnow() + timedelta(hours=1)
    
    # Create the token record
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=expires_at
    )
    
    db.session.add(reset_token)
    db.session.commit()
    
    return token

def send_password_reset_email(user, token):
    """Send password reset email to user"""
    # Create reset URL
    reset_url = f"{request.url_root}reset-password/{token}"
    
    # Get sender name from environment
    from_name = os.getenv('RESEND_FROM_NAME', 'ChatBot Platform')
    
    # Create email content
    subject = "Password Reset Request"
    body = f"""
Dear {user.username},

You have requested to reset your password for your Chatbot Platform account.

To reset your password, please click the link below:
{reset_url}

This link will expire in 1 hour for security reasons.

If you did not request this password reset, please ignore this email and your password will remain unchanged.

Best regards,
{from_name}
    """
    
    # Send email using Resend
    send_email(user.email, subject, body)

# Admin authentication
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            # For AJAX requests, return JSON error instead of redirect
            if (request.headers.get('Content-Type') == 'application/json' or 
                request.is_json or 
                request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
                return jsonify({'success': False, 'message': 'Authentication required'}), 401
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

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

def encode_image_to_base64(file):
    """Convert uploaded file to base64 data URL"""
    import base64
    import mimetypes
    
    if not file or not file.filename:
        return None
    
    # Get file extension and MIME type
    file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
    mime_type = mimetypes.guess_type(file.filename)[0] or f'image/{file_ext}'
    
    # Read file content and encode
    file_content = file.read()
    file.seek(0)  # Reset file pointer for potential future use
    
    base64_content = base64.b64encode(file_content).decode('utf-8')
    return f"data:{mime_type};base64,{base64_content}"

def get_logo_url(site_settings):
    """Get logo URL - either base64 data URL or file URL"""
    if site_settings.logo_base64:
        return site_settings.logo_base64
    elif site_settings.logo_filename:
        return url_for('static', filename='uploads/' + site_settings.logo_filename)
    return None

def get_hero_icon_url(site_settings):
    """Get hero icon URL - either base64 data URL or file URL"""
    if site_settings.hero_icon_base64:
        return site_settings.hero_icon_base64
    elif site_settings.hero_icon_filename:
        return url_for('static', filename='uploads/' + site_settings.hero_icon_filename)
    return None

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
    
    # Add custom Jinja2 function for avatar URL
    @app.template_global()
    def get_avatar_url(avatar_filename):
        if not avatar_filename:
            return None
        
        # Check if it's a predefined avatar
        allowed_predefined = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']
        if avatar_filename in allowed_predefined:
            return url_for('static', filename='avatars/' + avatar_filename)
        else:
            return url_for('static', filename='uploads/' + avatar_filename)
    
    # Add custom Jinja2 function for getting settings
    @app.template_global()
    def get_setting(key, default=None):
        """Get a setting value from the database"""
        setting = Settings.query.filter_by(key=key).first()
        return setting.value if setting else default
    
    @app.template_global()
    def get_logo_url(site_settings):
        """Get logo URL - either base64 data URL or file URL"""
        if site_settings and site_settings.logo_base64:
            return site_settings.logo_base64
        elif site_settings and site_settings.logo_filename:
            return url_for('static', filename='uploads/' + site_settings.logo_filename)
        return None
    
    @app.template_global()
    def get_hero_icon_url(site_settings):
        """Get hero icon URL - either base64 data URL or file URL"""
        if site_settings and site_settings.hero_icon_base64:
            return site_settings.hero_icon_base64
        elif site_settings and site_settings.hero_icon_filename:
            return url_for('static', filename='uploads/' + site_settings.hero_icon_filename)
        return None
    
    # Handle PostgreSQL URL for Render.com
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///chatbot_platform.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # Use Render disk path if available, otherwise fallback to local uploads
    render_disk_path = os.environ.get('RENDER_DISK_PATH', '/uploads')
    if os.path.exists(render_disk_path):
        app.config['UPLOAD_FOLDER'] = render_disk_path
        print(f"Using Render disk: {render_disk_path}")
    else:
        app.config['UPLOAD_FOLDER'] = 'uploads'
        print(f"WARNING: Render disk not found at {render_disk_path}, using local: uploads")
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
                print(f"WARNING: {e}")
                print("INFO: OpenAI service not available. Some features may be limited.")
                return None
        return chat_service

    # Routes

    @app.before_request
    def attach_user_plan_to_current_user():
        # Ensure templates like plans can read current_user.user_plan reliably
        try:
            if current_user.is_authenticated:
                try:
                    current_user.user_plan = get_user_plan(current_user)
                except Exception:
                    current_user.user_plan = None
            else:
                # Attribute exists but is None when anonymous
                current_user.user_plan = None
        except Exception:
            pass

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
        
        # Get active homepage sections ordered by order field
        homepage_sections = HomepageSection.query.filter_by(is_active=True).order_by(HomepageSection.order.asc(), HomepageSection.created_at.asc()).all()
        
        return render_template('index.html',
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder,
                             homepage_sections=homepage_sections)

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
                # Get active FAQ items for error case
                faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
                
                # Get homepage chatbot settings for chatbot display
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
                
                return render_template('contact.html', 
                                     faqs=faqs,
                                     homepage_chatbot=homepage_chatbot,
                                     homepage_chatbot_title=homepage_chatbot_title,
                                     homepage_chatbot_placeholder=homepage_chatbot_placeholder)
            
            # Email validation
            if '@' not in email or '.' not in email:
                flash('Please enter a valid email address.', 'error')
                # Get active FAQ items for error case
                faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
                
                # Get homepage chatbot settings for chatbot display
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
                
                return render_template('contact.html', 
                                     faqs=faqs,
                                     homepage_chatbot=homepage_chatbot,
                                     homepage_chatbot_title=homepage_chatbot_title,
                                     homepage_chatbot_placeholder=homepage_chatbot_placeholder)
            
            try:
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
                admin_email = os.getenv('RESEND_ADMIN_EMAIL')
                if not admin_email:
                    flash('Admin email not configured. Please contact the administrator.', 'error')
                    # Get active FAQ items for error case
                    faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
                    
                    # Get homepage chatbot settings for chatbot display
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
                    
                    return render_template('contact.html', 
                                         faqs=faqs,
                                         homepage_chatbot=homepage_chatbot,
                                         homepage_chatbot_title=homepage_chatbot_title,
                                         homepage_chatbot_placeholder=homepage_chatbot_placeholder)
                
                send_email(admin_email, email_subject, email_body)
                
                # Send confirmation email to user
                from_name = os.getenv('RESEND_FROM_NAME', 'ChatBot Platform')
                confirmation_subject = "Thank you for contacting us"
                confirmation_body = f"""
Dear {name},

Thank you for contacting us. We have received your message and will get back to you as soon as possible.

Your message:
Subject: {subject}
Message: {message}

Best regards,
{from_name}
                """
                
                send_email(email, confirmation_subject, confirmation_body)
                
                flash('Thank you for your message! We will get back to you soon.', 'success')
                return redirect(url_for('contact'))
                
            except Exception as e:
                flash(f'Failed to send message. Please try again later. Error: {str(e)}', 'error')
                # Get active FAQ items for error case
                faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
                
                # Get homepage chatbot settings for chatbot display
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
                
                return render_template('contact.html', 
                                     faqs=faqs,
                                     homepage_chatbot=homepage_chatbot,
                                     homepage_chatbot_title=homepage_chatbot_title,
                                     homepage_chatbot_placeholder=homepage_chatbot_placeholder)
        
        # Get active FAQ items ordered by order field
        faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
        
        # Get homepage chatbot settings for chatbot display
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
        
        return render_template('contact.html', 
                             faqs=faqs,
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/plans')
    def plans():
        plans = Plan.query.filter_by(is_active=True).order_by(Plan.monthly_price.asc()).all()
        
        # Get homepage chatbot settings for chatbot display
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
        
        return render_template('plans.html', 
                             plans=plans,
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            username = request.form['username']
            email = request.form['email']
            password = request.form['password']
            business_name = request.form.get('business_name', '').strip()
            website = request.form.get('website', '').strip()
            
            if User.query.filter_by(username=username).first():
                flash('Username already exists')
                return redirect(url_for('register'))
            
            if User.query.filter_by(email=email).first():
                flash('Email already exists')
                return redirect(url_for('register'))
            
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                business_name=business_name if business_name else None,
                website=website if website else None
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

    @app.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        if request.method == 'POST':
            email = request.form.get('email', '').strip()
            
            if not email:
                flash('Please enter your email address.', 'error')
                return render_template('forgot_password.html')
            
            # Find user by email
            user = User.query.filter_by(email=email).first()
            
            if user:
                try:
                    # Generate reset token
                    token = generate_password_reset_token(user)
                    
                    # Send reset email
                    send_password_reset_email(user, token)
                    
                    flash('Password reset instructions have been sent to your email address.', 'success')
                    return redirect(url_for('login'))
                    
                except Exception as e:
                    flash(f'Failed to send reset email. Please try again later. Error: {str(e)}', 'error')
                    return render_template('forgot_password.html')
            else:
                # Don't reveal if email exists or not for security
                flash('If an account with that email exists, password reset instructions have been sent.', 'info')
                return redirect(url_for('login'))
        
        return render_template('forgot_password.html')

    @app.route('/reset-password/<token>', methods=['GET', 'POST'])
    def reset_password(token):
        # Find the token
        reset_token = PasswordResetToken.query.filter_by(token=token, used=False).first()
        
        if not reset_token:
            flash('Invalid or expired reset token.', 'error')
            return redirect(url_for('login'))
        
        # Check if token is expired
        if datetime.utcnow() > reset_token.expires_at:
            flash('Reset token has expired. Please request a new password reset.', 'error')
            return redirect(url_for('forgot_password'))
        
        if request.method == 'POST':
            password = request.form.get('password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            # Validate passwords
            if not password or not confirm_password:
                flash('Please fill in all fields.', 'error')
                return render_template('reset_password.html', token=token)
            
            if password != confirm_password:
                flash('Passwords do not match.', 'error')
                return render_template('reset_password.html', token=token)
            
            if len(password) < 6:
                flash('Password must be at least 6 characters long.', 'error')
                return render_template('reset_password.html', token=token)
            
            try:
                # Update user password
                user = reset_token.user
                user.password_hash = generate_password_hash(password)
                
                # Mark token as used
                reset_token.used = True
                
                db.session.commit()
                
                flash('Your password has been reset successfully. You can now log in with your new password.', 'success')
                return redirect(url_for('login'))
                
            except Exception as e:
                flash(f'Failed to reset password. Please try again later. Error: {str(e)}', 'error')
                return render_template('reset_password.html', token=token)
        
        return render_template('reset_password.html', token=token)

    @app.route('/dashboard')
    @login_required
    def dashboard():
        chatbots = Chatbot.query.filter_by(user_id=current_user.id).all()
        # Attach user_plan attribute for templates that may rely on it
        try:
            current_user.user_plan = get_user_plan(current_user)
        except Exception:
            current_user.user_plan = None
        current_chatbot_count = len(chatbots)
        remaining_chatbots = (current_user.user_plan.chatbot_limit - current_chatbot_count) if current_user.user_plan else 0
        
        # Get homepage chatbot settings for chatbot display
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
        
        return render_template('dashboard.html', 
                             chatbots=chatbots,
                             user_plan=current_user.user_plan,
                             current_chatbot_count=current_chatbot_count,
                             remaining_chatbots=remaining_chatbots,
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        if request.method == 'POST':
            # Handle profile updates
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            full_name = request.form.get('full_name', '').strip()
            business_name = request.form.get('business_name', '').strip()
            website = request.form.get('website', '').strip()
            current_password = request.form.get('current_password', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            # Validate required fields
            if not username or not email:
                flash('Username and email are required.', 'error')
                return render_template('profile.html')
            
            # Check if username is already taken by another user
            existing_user = User.query.filter(User.username == username, User.id != current_user.id).first()
            if existing_user:
                flash('Username is already taken.', 'error')
                return render_template('profile.html')
            
            # Check if email is already taken by another user
            existing_email = User.query.filter(User.email == email, User.id != current_user.id).first()
            if existing_email:
                flash('Email is already taken.', 'error')
                return render_template('profile.html')
            
            # Update basic profile info
            current_user.username = username
            current_user.email = email
            current_user.full_name = full_name if full_name else None
            current_user.business_name = business_name if business_name else None
            current_user.website = website if website else None
            
            # Handle password change if provided
            if new_password:
                if not current_password:
                    flash('Current password is required to change password.', 'error')
                    return render_template('profile.html')
                
                # Verify current password
                if not check_password_hash(current_user.password_hash, current_password):
                    flash('Current password is incorrect.', 'error')
                    return render_template('profile.html')
                
                if new_password != confirm_password:
                    flash('New passwords do not match.', 'error')
                    return render_template('profile.html')
                
                if len(new_password) < 6:
                    flash('New password must be at least 6 characters long.', 'error')
                    return render_template('profile.html')
                
                # Update password
                current_user.password_hash = generate_password_hash(new_password)
                flash('Password updated successfully.', 'success')
            
            try:
                db.session.commit()
                flash('Profile updated successfully.', 'success')
                return redirect(url_for('profile'))
            except Exception as e:
                db.session.rollback()
                flash(f'Failed to update profile. Please try again. Error: {str(e)}', 'error')
                return render_template('profile.html')
        
        return render_template('profile.html')

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
            greeting_message = request.form.get('greeting_message', '').strip()
            
            # Use default prompt if none provided
            if not system_prompt:
                system_prompt = "You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge."
            
            # Handle avatar selection (custom upload or predefined)
            avatar_filename = None
            
            # Check for predefined avatar selection first
            selected_avatar = request.form.get('selected_avatar')
            if selected_avatar:
                # Validate that the selected avatar exists in our predefined avatars
                allowed_predefined = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']
                if selected_avatar in allowed_predefined:
                    avatar_filename = selected_avatar
                else:
                    flash('Invalid predefined avatar selection.', 'error')
                    return redirect(url_for('create_chatbot'))
            
            # If no predefined avatar selected, check for custom upload
            elif 'avatar' in request.files:
                avatar_file = request.files['avatar']
                if avatar_file and avatar_file.filename:
                    # Check if file is allowed
                    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                    if '.' in avatar_file.filename and \
                       avatar_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                        
                        # Create uploads directory if it doesn't exist
                        upload_dir = os.path.join(app.root_path, 'static', 'uploads')
                        os.makedirs(upload_dir, exist_ok=True)
                        
                        # Generate secure filename
                        filename = secure_filename(avatar_file.filename)
                        # Add timestamp to avoid conflicts
                        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                        name_part, ext = os.path.splitext(filename)
                        avatar_filename = f"avatar_{name_part}_{timestamp}{ext}"
                        
                        # Save file
                        avatar_path = os.path.join(upload_dir, avatar_filename)
                        avatar_file.save(avatar_path)
                    else:
                        flash('Invalid avatar file type. Please upload PNG, JPG, GIF, or SVG files.', 'error')
                        return redirect(url_for('create_chatbot'))
            
            chatbot = Chatbot(
                name=name,
                description=description,
                system_prompt=system_prompt,
                embed_code=str(uuid.uuid4()),
                user_id=current_user.id,
                avatar_filename=avatar_filename,
                greeting_message=greeting_message if greeting_message else None
            )
            
            db.session.add(chatbot)
            db.session.commit()
            
            flash('Chatbot created successfully!')
            return redirect(url_for('chatbot_details', chatbot_id=chatbot.id))
        
        # Get user's plan info for display
        user_plan = get_user_plan(current_user)
        current_chatbot_count = Chatbot.query.filter_by(user_id=current_user.id).count()
        remaining_chatbots = user_plan.chatbot_limit - current_chatbot_count
        
        # Get homepage chatbot settings for chatbot display
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
        
        return render_template('create_chatbot.html', 
                             user_plan=user_plan, 
                             current_chatbot_count=current_chatbot_count,
                             remaining_chatbots=remaining_chatbots,
                             homepage_chatbot=homepage_chatbot,
                             homepage_chatbot_title=homepage_chatbot_title,
                             homepage_chatbot_placeholder=homepage_chatbot_placeholder)

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
        greeting_message = request.form.get('greeting_message', '').strip()
        
        # Update fields
        chatbot.description = description if description else None
        chatbot.greeting_message = greeting_message if greeting_message else None
        
        if system_prompt:
            chatbot.system_prompt = system_prompt
        else:
            chatbot.system_prompt = "You are a helpful AI assistant. Answer questions based on the provided documents and your general knowledge."
        
        # Handle avatar selection (custom upload or predefined)
        selected_avatar = request.form.get('selected_avatar')
        if selected_avatar:
            # Validate that the selected avatar exists in our predefined avatars
            allowed_predefined = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']
            if selected_avatar in allowed_predefined:
                # Delete old custom avatar if exists (only if it's not a predefined one)
                if chatbot.avatar_filename and not chatbot.avatar_filename in allowed_predefined:
                    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
                    old_avatar_path = os.path.join(upload_dir, chatbot.avatar_filename)
                    if os.path.exists(old_avatar_path):
                        os.remove(old_avatar_path)
                
                chatbot.avatar_filename = selected_avatar
            else:
                flash('Invalid predefined avatar selection.', 'error')
                return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
        
        elif 'avatar' in request.files:
            avatar_file = request.files['avatar']
            if avatar_file and avatar_file.filename:
                # Check if file is allowed
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                if '.' in avatar_file.filename and \
                   avatar_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    
                    # Create uploads directory if it doesn't exist
                    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    # Delete old avatar if exists (only if it's a custom upload, not predefined)
                    if chatbot.avatar_filename:
                        allowed_predefined = ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png']
                        if chatbot.avatar_filename not in allowed_predefined:
                            old_avatar_path = os.path.join(upload_dir, chatbot.avatar_filename)
                            if os.path.exists(old_avatar_path):
                                os.remove(old_avatar_path)
                    
                    # Generate secure filename
                    filename = secure_filename(avatar_file.filename)
                    # Add timestamp to avoid conflicts
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    name_part, ext = os.path.splitext(filename)
                    avatar_filename = f"avatar_{name_part}_{timestamp}{ext}"
                    
                    # Save file
                    avatar_path = os.path.join(upload_dir, avatar_filename)
                    avatar_file.save(avatar_path)
                    chatbot.avatar_filename = avatar_filename
                else:
                    flash('Invalid avatar file type. Please upload PNG, JPG, GIF, or SVG files.', 'error')
                    return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
        
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
            # Check file size limit based on user's plan
            user_plan = get_user_plan(current_user)
            file_size_limit_bytes = user_plan.file_size_limit_mb * 1024 * 1024  # Convert MB to bytes
            
            # Get file size
            file.seek(0, 2)  # Seek to end of file
            file_size = file.tell()
            file.seek(0)  # Reset file pointer
            
            if file_size > file_size_limit_bytes:
                flash(f'File size ({file_size / (1024*1024):.1f}MB) exceeds your plan limit ({user_plan.file_size_limit_mb}MB). Please upgrade your plan or use a smaller file.', 'error')
                return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
            
            filename = secure_filename(file.filename)
            
            # Check if a document with the same original filename already exists for this chatbot
            existing_document = Document.query.filter_by(
                original_filename=filename, 
                chatbot_id=chatbot_id
            ).first()
            
            if existing_document:
                # Delete the old file from filesystem
                try:
                    if os.path.exists(existing_document.file_path):
                        os.remove(existing_document.file_path)
                except OSError:
                    pass  # File might already be deleted, continue
                
                # Update the existing document record
                unique_filename = f"{uuid.uuid4()}_{filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                
                try:
                    file.save(file_path)
                    # Verify file was actually saved
                    if not os.path.exists(file_path):
                        raise OSError("File save failed - file not found after save")
                    
                    existing_document.filename = unique_filename
                    existing_document.file_path = file_path
                    existing_document.uploaded_at = datetime.utcnow()
                    existing_document.processed = False  # Mark as unprocessed so it gets retrained
                    
                    db.session.commit()
                    flash(f'Document "{filename}" has been updated successfully!')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error saving file: {str(e)}. Please try again.')
                    return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
            else:
                # Create new document
                unique_filename = f"{uuid.uuid4()}_{filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                
                try:
                    file.save(file_path)
                    # Verify file was actually saved
                    if not os.path.exists(file_path):
                        raise OSError("File save failed - file not found after save")
                    
                    document = Document(
                        filename=unique_filename,
                        original_filename=filename,
                        file_path=file_path,
                        chatbot_id=chatbot_id
                    )
                    
                    db.session.add(document)
                    db.session.commit()
                    
                    flash('Document uploaded successfully!')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error saving file: {str(e)}. Please try again.')
                    return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
        else:
            flash('Invalid file type. Please upload PDF, DOCX, TXT, or JSON files.')
        
        return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))

    @app.route('/delete_document/<int:document_id>', methods=['POST'])
    @login_required
    def delete_document(document_id):
        # Get the document and verify ownership
        document = Document.query.get_or_404(document_id)
        chatbot = Chatbot.query.filter_by(id=document.chatbot_id, user_id=current_user.id).first_or_404()
        
        try:
            # Delete the physical file if it exists
            if os.path.exists(document.file_path):
                os.remove(document.file_path)
            
            # Delete the document record from database
            db.session.delete(document)
            db.session.commit()
            
            # If chatbot was trained, mark it as needing retraining
            if chatbot.is_trained:
                chatbot.is_trained = False
                db.session.commit()
                flash('Document deleted successfully! The chatbot will need to be retrained.')
            else:
                flash('Document deleted successfully!')
                
        except Exception as e:
            flash(f'Error deleting document: {str(e)}')
        
        return redirect(url_for('chatbot_details', chatbot_id=chatbot.id))

    @app.route('/download_document/<int:document_id>')
    @login_required
    def download_document(document_id):
        # Get the document and verify ownership
        document = Document.query.get_or_404(document_id)
        chatbot = Chatbot.query.filter_by(id=document.chatbot_id, user_id=current_user.id).first_or_404()
        
        # Resolve the actual file path - handle both absolute and relative paths
        file_path = document.file_path
        
        # Check if file exists as-is
        if not os.path.exists(file_path):
            # Try with just the filename in the upload folder
            alt_path = os.path.join(app.config['UPLOAD_FOLDER'], document.filename)
            if os.path.exists(alt_path):
                file_path = alt_path
            else:
                # Handle cross-platform path issues (Windows backslashes on Linux)
                # Extract just the filename from the stored path
                filename_only = os.path.basename(file_path.replace('\\', '/'))
                alt_path = os.path.join(app.config['UPLOAD_FOLDER'], filename_only)
                if os.path.exists(alt_path):
                    file_path = alt_path
                else:
                    flash(f'File not found on server. Please re-upload the document.')
                    return redirect(url_for('chatbot_details', chatbot_id=chatbot.id))
        
        try:
            return send_file(
                file_path,
                as_attachment=True,
                download_name=document.original_filename,
                mimetype='application/octet-stream'
            )
        except Exception as e:
            flash(f'Error downloading file: {str(e)}')
            return redirect(url_for('chatbot_details', chatbot_id=chatbot.id))

    @app.route('/train_chatbot/<int:chatbot_id>', methods=['POST'])
    @login_required
    def train_chatbot(chatbot_id):
        chatbot = Chatbot.query.filter_by(id=chatbot_id, user_id=current_user.id).first_or_404()
        documents = Document.query.filter_by(chatbot_id=chatbot_id).all()
        
        if not documents:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': 'Please upload at least one document before training.'})
            flash('Please upload at least one document before training.')
            return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
        
        try:
            # Process all documents for this chatbot
            all_text = ""
            for doc in documents:
                # Resolve the actual file path - handle both absolute and relative paths
                file_path = doc.file_path
                
                # If file_path doesn't exist as-is, try to resolve it
                if not os.path.exists(file_path):
                    # Try with just the filename in the upload folder
                    alt_path = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
                    if os.path.exists(alt_path):
                        file_path = alt_path
                    else:
                        # Handle cross-platform path issues (Windows backslashes on Linux)
                        # Extract just the filename from the stored path
                        filename_only = os.path.basename(file_path.replace('\\', '/'))
                        alt_path = os.path.join(app.config['UPLOAD_FOLDER'], filename_only)
                        if os.path.exists(alt_path):
                            file_path = alt_path
                        else:
                            raise FileNotFoundError(f"Document file not found: {doc.original_filename} (tried: {doc.file_path}, {alt_path})")
                
                text = document_processor.process_document(file_path)
                all_text += f"\n\n{text}"
                doc.processed = True
            
            # Commit document processing status first
            db.session.commit()
            
            # Train the chatbot with knowledge base generation
            chatbot_info = {
                'name': chatbot.name,
                'description': chatbot.description or ''
            }
            chatbot_trainer.train_chatbot(chatbot_id, all_text, use_knowledge_base=True, chatbot_info=chatbot_info)
            chatbot.is_trained = True
            db.session.commit()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Chatbot trained successfully!'})
            flash('Chatbot trained successfully!')
            return redirect(url_for('chatbot_details', chatbot_id=chatbot_id))
            
        except Exception as e:
            # Even if training fails, documents are already marked as processed
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': str(e)})
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
                
            # Check if this is an end conversation action
            action = data.get('action')
            if action == 'end_conversation':
                conversation_id = data.get('conversation_id')
                resolved = data.get('resolved', False)
                
                if conversation_id:
                    # Update conversation status in database
                    # Since conversation_id is a UUID string, we need to find conversations by chatbot_id
                    # and update the most recent ones or all conversations for this chatbot
                    conversations = Conversation.query.filter_by(chatbot_id=chatbot.id).all()
                    for conv in conversations:
                        conv.response_status = 'resolved' if resolved else 'active'
                    db.session.commit()
                    
                    return jsonify({
                        'success': True,
                        'message': 'Conversation status updated',
                        'conversation_id': conversation_id
                    })
                else:
                    return jsonify({'error': 'Conversation ID required for end conversation action'}), 400
            
            user_message = data.get('message', '').strip()
            conversation_id = data.get('conversation_id', None)
            
            if not user_message:
                return jsonify({'error': 'Message is required'}), 400
            
            # Generate conversation ID if not provided (for new conversations)
            if not conversation_id:
                conversation_id = str(uuid.uuid4())
                print(f"🆕 DEBUG: Generated new conversation ID: {conversation_id}")
            else:
                print(f"🔄 DEBUG: Continuing conversation: {conversation_id}")
            
            print(f"🤖 Chat API: Processing message for chatbot {chatbot.id}: '{user_message}'")
            
            # Import and use the ChatService for better response handling
            try:
                from services.chat_service import ChatService
                print(f"[OK] Successfully imported ChatService")
                chat_service = ChatService()
                print(f"[OK] Successfully created ChatService instance")
            except Exception as e:
                print(f"[ERROR] Failed to import/create ChatService: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': f'Service initialization failed: {str(e)}'}), 500
            
            # Try to use OpenAI service first, fallback to local chat service
            openai_service = get_chat_service()
            if openai_service and hasattr(openai_service, 'get_response'):
                try:
                    print(f"🔄 Trying OpenAI service")
                    response = openai_service.get_response(chatbot.id, user_message, conversation_id)
                    print(f"[OK] OpenAI response generated")
                except Exception as e:
                    print(f"[WARNING] OpenAI service failed: {e}, falling back to local chat service")
                    try:
                        response = chat_service.get_response(chatbot.id, user_message)
                        print(f"[OK] Local chat service response generated")
                    except Exception as e2:
                        print(f"[ERROR] Local chat service also failed: {e2}")
                        return jsonify({'error': f'Both services failed. OpenAI: {str(e)}, Local: {str(e2)}'}), 500
            else:
                # Use local chat service (better than direct trainer)
                print(f"🔄 Using local chat service")
                try:
                    response = chat_service.get_response(chatbot.id, user_message)
                    print(f"[OK] Local chat service response generated")
                except Exception as e:
                    print(f"[ERROR] Local chat service failed: {e}")
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
            return jsonify({'response': response, 'conversation_id': conversation_id})
            
        except Exception as e:
            print(f"[ERROR] Chat API Error: {str(e)}")
            print(f"[ERROR] Error type: {type(e).__name__}")
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
        chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
        if not chatbot:
            return "Chatbot not found", 404
        return render_template('embed.html', embed_code=embed_code, chatbot=chatbot)

    @app.route('/test-embed')
    def test_embed():
        # Get the first available chatbot for testing
        chatbot = Chatbot.query.first()
        if chatbot:
            return render_template('embed.html', embed_code=chatbot.embed_code, chatbot=chatbot)
        return "No chatbots available for testing"
    
    @app.route('/uploads/<filename>')
    def uploaded_file(filename):
        """Serve uploaded avatar images"""
        return send_from_directory(os.path.join(app.root_path, 'static', 'uploads'), filename)
    
    @app.route('/preview/<embed_code>')
    def preview_chatbot(embed_code):
        """Preview chatbot on a sample business website"""
        chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
        if not chatbot:
            return "Chatbot not found", 404
        return render_template('preview.html', embed_code=embed_code, chatbot=chatbot)
    
    @app.route('/web-preview/<embed_code>')
    def web_preview_chatbot(embed_code):
        """Web preview chatbot on user's actual business website"""
        chatbot = Chatbot.query.filter_by(embed_code=embed_code).first()
        if not chatbot:
            return "Chatbot not found", 404
        
        # Check if user has a website URL
        if not chatbot.owner.website:
            return render_template('web_preview_no_website.html', chatbot=chatbot)
        
        return render_template('web_preview.html', embed_code=embed_code, chatbot=chatbot)
    
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
        
        # Get database information
        from database_export import get_database_info
        db_info = get_database_info()
        
        return render_template('admin/dashboard.html', 
                             total_users=total_users,
                             total_chatbots=total_chatbots,
                             trained_chatbots=trained_chatbots,
                             total_conversations=total_conversations,
                             recent_users=recent_users,
                             recent_chatbots=recent_chatbots,
                             recent_conversations=recent_conversations,
                             db_info=db_info)

    @app.route('/admin/export-database')
    @admin_required
    def admin_export_database():
        """Export the entire database as SQL statements"""
        try:
            from database_export import export_database_to_sql
            import os
            from flask import send_file, flash
            
            # Export the database
            export_path = export_database_to_sql()
            
            # Check if file was created successfully
            if os.path.exists(export_path):
                flash(f'Database backup created successfully: {os.path.basename(export_path)}')
                
                # Send the file for download
                return send_file(
                    export_path,
                    as_attachment=True,
                    download_name=f'database_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sql',
                    mimetype='application/sql'
                )
            else:
                flash('Failed to create database backup', 'error')
                return redirect(url_for('admin_dashboard'))
                
        except Exception as e:
            flash(f'Error creating database backup: {str(e)}', 'error')
            return redirect(url_for('admin_dashboard'))

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

    @app.route('/admin/chatbots/<int:chatbot_id>')
    @admin_required
    def admin_chatbot_details(chatbot_id):
        """Admin view of chatbot details - can view any chatbot"""
        chatbot = Chatbot.query.get_or_404(chatbot_id)
        documents = Document.query.filter_by(chatbot_id=chatbot_id).all()
        conversations = Conversation.query.filter_by(chatbot_id=chatbot_id).order_by(Conversation.timestamp.desc()).limit(50).all()
        
        # Get the owner's plan
        owner_plan = get_user_plan(chatbot.owner)
        
        return render_template('admin/chatbot_details.html', 
                             chatbot=chatbot, 
                             documents=documents, 
                             conversations=conversations,
                             owner_plan=owner_plan)

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
            section = request.form.get('section')
            print(f"DEBUG: Processing section: {section}")
            print(f"DEBUG: Form data: {dict(request.form)}")
            
            if section == 'homepage':
                # Update homepage chatbot settings only
                print("DEBUG: Processing homepage section")
                homepage_chatbot_id = request.form.get('homepage_chatbot_id')
                homepage_chatbot_title = request.form.get('homepage_chatbot_title', 'Platform Assistant')
                homepage_chatbot_placeholder = request.form.get('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
                
                print(f"DEBUG: Homepage values - ID: {homepage_chatbot_id}, Title: {homepage_chatbot_title}, Placeholder: {homepage_chatbot_placeholder}")
                
                set_setting('homepage_chatbot_id', homepage_chatbot_id)
                set_setting('homepage_chatbot_title', homepage_chatbot_title)
                set_setting('homepage_chatbot_placeholder', homepage_chatbot_placeholder)
                
                flash('Homepage settings updated successfully!')
                
            elif section == 'contact':
                # Update contact page settings only
                print("DEBUG: Processing contact section")
                contact_email = request.form.get('contact_email', 'support@owlbee.ai')
                contact_response_time = request.form.get('contact_response_time', 'We typically respond within 24 hours')
                contact_support_hours = request.form.get('contact_support_hours', 'Monday - Friday\n9:00 AM - 6:00 PM (EST)')
                contact_live_chat_text = request.form.get('contact_live_chat_text', 'Try our Platform Assistant chatbot in the bottom-right corner for instant help!')
                
                print(f"DEBUG: Contact values - Email: {contact_email}, Response Time: {contact_response_time}")
                
                set_setting('contact_email', contact_email)
                set_setting('contact_response_time', contact_response_time)
                set_setting('contact_support_hours', contact_support_hours)
                set_setting('contact_live_chat_text', contact_live_chat_text)
                
                flash('Contact page settings updated successfully!')
                
            elif section == 'openai':
                # Update OpenAI model settings only
                print("DEBUG: Processing openai section")
                openai_model = request.form.get('openai_model', 'gpt-3.5-turbo').strip()
                print(f"DEBUG: OpenAI model: {openai_model}")
                set_setting('openai_model', openai_model)
                
                flash('OpenAI model settings updated successfully!')
                
            elif section == 'stripe':
                # Update Stripe settings only
                print("DEBUG: Processing stripe section")
                stripe_publishable_key = request.form.get('stripe_publishable_key', '').strip()
                stripe_secret_key = request.form.get('stripe_secret_key', '').strip()
                stripe_webhook_secret = request.form.get('stripe_webhook_secret', '').strip()
                
                set_setting('stripe_publishable_key', stripe_publishable_key)
                set_setting('stripe_secret_key', stripe_secret_key)
                set_setting('stripe_webhook_secret', stripe_webhook_secret)
                
                flash('Stripe settings updated successfully!')
            else:
                print(f"DEBUG: Unknown section: {section}")
                flash('Unknown section. No settings updated.')
            
            return redirect(url_for('admin_settings'))
        
        # Get current homepage settings
        current_chatbot_id = get_setting('homepage_chatbot_id')
        current_title = get_setting('homepage_chatbot_title', 'Platform Assistant')
        current_placeholder = get_setting('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
        
        # Get current contact page settings
        current_contact_email = get_setting('contact_email', 'support@owlbee.ai')
        current_contact_response_time = get_setting('contact_response_time', 'We typically respond within 24 hours')
        current_contact_support_hours = get_setting('contact_support_hours', 'Monday - Friday\n9:00 AM - 6:00 PM (EST)')
        current_contact_live_chat_text = get_setting('contact_live_chat_text', 'Try our Platform Assistant chatbot in the bottom-right corner for instant help!')
        
        # Get current Stripe settings
        current_stripe_publishable_key = get_setting('stripe_publishable_key', '')
        current_stripe_secret_key = get_setting('stripe_secret_key', '')
        current_stripe_webhook_secret = get_setting('stripe_webhook_secret', '')
        
        # Get current OpenAI model setting
        current_openai_model = get_setting('openai_model', 'gpt-3.5-turbo')
        
        # Get current training prompt
        current_training_prompt = get_setting('training_prompt', '')
        
        # Get all trained chatbots for selection
        trained_chatbots = Chatbot.query.filter_by(is_trained=True).all()
        
        # Get current chatbot object if configured
        current_chatbot = None
        if current_chatbot_id:
            current_chatbot = Chatbot.query.get(current_chatbot_id)
        
        return render_template('admin/settings.html',
                             current_chatbot_id=current_chatbot_id,
                             current_chatbot=current_chatbot,
                             current_title=current_title,
                             current_placeholder=current_placeholder,
                             current_contact_email=current_contact_email,
                             current_contact_response_time=current_contact_response_time,
                             current_contact_support_hours=current_contact_support_hours,
                             current_contact_live_chat_text=current_contact_live_chat_text,
                             current_stripe_publishable_key=current_stripe_publishable_key,
                             current_stripe_secret_key=current_stripe_secret_key,
                             current_stripe_webhook_secret=current_stripe_webhook_secret,
                             current_openai_model=current_openai_model,
                             current_training_prompt=current_training_prompt,
                             trained_chatbots=trained_chatbots)

    @app.route('/admin/settings/homepage', methods=['POST'])
    @admin_required
    def admin_settings_homepage():
        """AJAX endpoint for homepage settings"""
        try:
            homepage_chatbot_id = request.form.get('homepage_chatbot_id')
            homepage_chatbot_title = request.form.get('homepage_chatbot_title', 'Platform Assistant')
            homepage_chatbot_placeholder = request.form.get('homepage_chatbot_placeholder', 'Ask me anything about the platform...')
            
            set_setting('homepage_chatbot_id', homepage_chatbot_id)
            set_setting('homepage_chatbot_title', homepage_chatbot_title)
            set_setting('homepage_chatbot_placeholder', homepage_chatbot_placeholder)
            
            return {'success': True, 'message': 'Homepage settings updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating homepage settings: {str(e)}'}, 500

    @app.route('/admin/settings/contact', methods=['POST'])
    @admin_required
    def admin_settings_contact():
        """AJAX endpoint for contact settings"""
        try:
            contact_email = request.form.get('contact_email', 'support@owlbee.ai')
            contact_response_time = request.form.get('contact_response_time', 'We typically respond within 24 hours')
            contact_support_hours = request.form.get('contact_support_hours', 'Monday - Friday\n9:00 AM - 6:00 PM (EST)')
            contact_live_chat_text = request.form.get('contact_live_chat_text', 'Try our Platform Assistant chatbot in the bottom-right corner for instant help!')
            
            set_setting('contact_email', contact_email)
            set_setting('contact_response_time', contact_response_time)
            set_setting('contact_support_hours', contact_support_hours)
            set_setting('contact_live_chat_text', contact_live_chat_text)
            
            return {'success': True, 'message': 'Contact settings updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating contact settings: {str(e)}'}, 500

    @app.route('/admin/settings/openai', methods=['POST'])
    @admin_required
    def admin_settings_openai():
        """AJAX endpoint for OpenAI settings"""
        try:
            openai_model = request.form.get('openai_model', 'gpt-3.5-turbo').strip()
            set_setting('openai_model', openai_model)
            
            return {'success': True, 'message': 'OpenAI model settings updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating OpenAI settings: {str(e)}'}, 500

    @app.route('/admin/settings/stripe', methods=['POST'])
    @admin_required
    def admin_settings_stripe():
        """AJAX endpoint for Stripe settings"""
        try:
            stripe_publishable_key = request.form.get('stripe_publishable_key', '').strip()
            stripe_secret_key = request.form.get('stripe_secret_key', '').strip()
            stripe_webhook_secret = request.form.get('stripe_webhook_secret', '').strip()
            
            set_setting('stripe_publishable_key', stripe_publishable_key)
            set_setting('stripe_secret_key', stripe_secret_key)
            set_setting('stripe_webhook_secret', stripe_webhook_secret)
            
            return {'success': True, 'message': 'Stripe settings updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating Stripe settings: {str(e)}'}, 500

    @app.route('/admin/settings/training-prompt', methods=['POST'])
    @admin_required
    def admin_settings_training_prompt():
        """AJAX endpoint for training prompt settings"""
        try:
            training_prompt = request.form.get('training_prompt', '').strip()
            
            if not training_prompt:
                return {'success': False, 'message': 'Training prompt cannot be empty'}, 400
            
            set_setting('training_prompt', training_prompt)
            
            return {'success': True, 'message': 'Training prompt updated successfully!'}
        except Exception as e:
            return {'success': False, 'message': f'Error updating training prompt: {str(e)}'}, 500

    def allowed_file(filename):
        ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'json'}
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    def create_demo_chatbot_internal():
        """Create a demo chatbot for the homepage if it doesn't exist"""
        demo_embed_code = 'a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb'
        
        # Check if demo chatbot already exists
        existing_chatbot = Chatbot.query.filter_by(embed_code=demo_embed_code).first()
        if existing_chatbot and existing_chatbot.is_trained:
            print(f"[OK] Demo chatbot already exists and is trained: {demo_embed_code}")
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
Upload relevant documents (manuals, FAQs, product information, policies) in PDF, DOCX, TXT, or JSON format. The platform will process these automatically.

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
            # Train demo chatbot with knowledge base generation
            demo_chatbot_info = {
                'name': demo_chatbot.name,
                'description': demo_chatbot.description or ''
            }
            chatbot_trainer.train_chatbot(demo_chatbot.id, demo_content, use_knowledge_base=True, chatbot_info=demo_chatbot_info)
            demo_chatbot.is_trained = True
            db.session.commit()
            print(f"[OK] Demo chatbot created and trained with embed code: {demo_embed_code}")
        except Exception as e:
            print(f"[WARNING] Demo chatbot created but training failed: {e}")
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
            file_size_limit_mb = int(request.form['file_size_limit_mb'])
            stripe_monthly_price_id = request.form.get('stripe_monthly_price_id', '').strip()
            stripe_yearly_price_id = request.form.get('stripe_yearly_price_id', '').strip()
            features_text = request.form.get('features', '')
            is_active = 'is_active' in request.form
            show_contact_sales = 'show_contact_sales' in request.form
            
            # Convert features text to JSON
            features_list = [feature.strip() for feature in features_text.split('\n') if feature.strip()]
            features_json = json.dumps(features_list)
            
            plan = Plan(
                name=name,
                description=description,
                monthly_price=monthly_price,
                yearly_price=yearly_price,
                chatbot_limit=chatbot_limit,
                file_size_limit_mb=file_size_limit_mb,
                stripe_monthly_price_id=stripe_monthly_price_id if stripe_monthly_price_id else None,
                stripe_yearly_price_id=stripe_yearly_price_id if stripe_yearly_price_id else None,
                features=features_json,
                is_active=is_active,
                show_contact_sales=show_contact_sales
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
            plan.file_size_limit_mb = int(request.form['file_size_limit_mb'])
            plan.stripe_monthly_price_id = request.form.get('stripe_monthly_price_id', '').strip()
            plan.stripe_yearly_price_id = request.form.get('stripe_yearly_price_id', '').strip()
            features_text = request.form.get('features', '')
            plan.is_active = 'is_active' in request.form
            plan.show_contact_sales = 'show_contact_sales' in request.form
            
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

    @app.route('/admin/resend-settings/test', methods=['POST'])
    @admin_required
    def admin_test_resend():
        try:
            # Send test email using Resend
            test_subject = "Resend Test Email"
            test_body = f"""
This is a test email from your Chatbot Platform using Resend.

Resend Configuration:
- From: {os.getenv('RESEND_FROM_NAME', 'ChatBot Platform')} <{os.getenv('RESEND_FROM_EMAIL')}>
- To: {os.getenv('RESEND_ADMIN_EMAIL')}

If you receive this email, your Resend configuration is working correctly!

Sent at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
            """
            
            admin_email = os.getenv('RESEND_ADMIN_EMAIL')
            if not admin_email:
                return jsonify({'success': False, 'message': 'RESEND_ADMIN_EMAIL not configured'})
            
            send_email(admin_email, test_subject, test_body)
            return jsonify({'success': True, 'message': 'Test email sent successfully!'})
            
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to send test email: {str(e)}'})

    @app.route('/admin/site-settings', methods=['GET', 'POST'])
    @admin_required
    def admin_site_settings():
        if request.method == 'POST':
            site_title = request.form['site_title']
            meta_tags = request.form.get('meta_tags', '').strip()
            hero_title = request.form.get('hero_title', '').strip()
            hero_subtitle = request.form.get('hero_subtitle', '').strip()
            
            # Handle logo upload - convert to base64
            logo_file = request.files.get('logo')
            logo_base64 = None
            
            # Handle hero icon upload - convert to base64
            hero_icon_file = request.files.get('hero_icon')
            hero_icon_base64 = None
            
            if logo_file and logo_file.filename:
                # Check if file is allowed
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                if '.' in logo_file.filename and \
                   logo_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    logo_base64 = encode_image_to_base64(logo_file)
            
            if hero_icon_file and hero_icon_file.filename:
                # Check if file is allowed
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
                if '.' in hero_icon_file.filename and \
                   hero_icon_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    hero_icon_base64 = encode_image_to_base64(hero_icon_file)
            
            # Get or create site settings
            site_settings = SiteSettings.query.filter_by(is_active=True).first()
            if not site_settings:
                site_settings = SiteSettings()
                db.session.add(site_settings)
            
            # Update settings
            site_settings.site_title = site_title
            site_settings.meta_tags = meta_tags
            site_settings.hero_title = hero_title
            site_settings.hero_subtitle = hero_subtitle
            
            if logo_base64:
                # Store base64 logo and clear old filename
                site_settings.logo_base64 = logo_base64
                site_settings.logo_filename = None  # Clear old filename
            
            if hero_icon_base64:
                # Store base64 hero icon and clear old filename
                site_settings.hero_icon_base64 = hero_icon_base64
                site_settings.hero_icon_filename = None  # Clear old filename
            
            db.session.commit()
            
            flash('Site settings updated successfully!')
            return redirect(url_for('admin_site_settings'))
        
        site_settings = get_site_settings()
        return render_template('admin/site_settings.html', site_settings=site_settings)

    @app.route('/admin/site-settings/delete-logo', methods=['POST'])
    @admin_required
    def admin_delete_logo():
        try:
            site_settings = SiteSettings.query.filter_by(is_active=True).first()
            if site_settings and (site_settings.logo_filename or site_settings.logo_base64):
                # Clear both filename and base64 data
                site_settings.logo_filename = None
                site_settings.logo_base64 = None
                db.session.commit()
                
                return jsonify({'success': True, 'message': 'Logo deleted successfully!'})
            else:
                return jsonify({'success': False, 'message': 'No logo to delete'})
                
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to delete logo: {str(e)}'})

    @app.route('/admin/site-settings/delete-hero-icon', methods=['POST'])
    @admin_required
    def admin_delete_hero_icon():
        try:
            site_settings = SiteSettings.query.filter_by(is_active=True).first()
            if site_settings and (site_settings.hero_icon_filename or site_settings.hero_icon_base64):
                # Clear both filename and base64 data
                site_settings.hero_icon_filename = None
                site_settings.hero_icon_base64 = None
                db.session.commit()
                
                return jsonify({'success': True, 'message': 'Hero icon deleted successfully!'})
            else:
                return jsonify({'success': False, 'message': 'No hero icon to delete'})
                
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to delete hero icon: {str(e)}'})

    # FAQ Management Routes
    @app.route('/admin/faq', methods=['GET', 'POST'])
    @admin_required
    def admin_faq():
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add':
                question = request.form.get('question', '').strip()
                answer = request.form.get('answer', '').strip()
                order = request.form.get('order', 0, type=int)
                
                if question and answer:
                    # Get the next order number if not specified
                    if order == 0:
                        max_order = db.session.query(db.func.max(FAQ.order)).scalar() or 0
                        order = max_order + 1
                    
                    faq = FAQ(question=question, answer=answer, order=order)
                    db.session.add(faq)
                    db.session.commit()
                    flash('FAQ question added successfully!')
                else:
                    flash('Both question and answer are required.', 'error')
            
            elif action == 'edit':
                faq_id = request.form.get('faq_id', type=int)
                question = request.form.get('question', '').strip()
                answer = request.form.get('answer', '').strip()
                order = request.form.get('order', 0, type=int)
                
                if faq_id and question and answer:
                    faq = FAQ.query.get_or_404(faq_id)
                    faq.question = question
                    faq.answer = answer
                    faq.order = order
                    faq.updated_at = datetime.utcnow()
                    db.session.commit()
                    flash('FAQ question updated successfully!')
                else:
                    flash('Invalid data provided.', 'error')
            
            elif action == 'delete':
                faq_id = request.form.get('faq_id', type=int)
                if faq_id:
                    faq = FAQ.query.get_or_404(faq_id)
                    db.session.delete(faq)
                    db.session.commit()
                    flash('FAQ question deleted successfully!')
                else:
                    flash('Invalid FAQ ID.', 'error')
            
            elif action == 'toggle':
                faq_id = request.form.get('faq_id', type=int)
                if faq_id:
                    faq = FAQ.query.get_or_404(faq_id)
                    faq.is_active = not faq.is_active
                    faq.updated_at = datetime.utcnow()
                    db.session.commit()
                    status = 'activated' if faq.is_active else 'deactivated'
                    flash(f'FAQ question {status} successfully!')
                else:
                    flash('Invalid FAQ ID.', 'error')
            
            return redirect(url_for('admin_faq'))
        
        # Get all FAQ items ordered by order field
        faqs = FAQ.query.order_by(FAQ.order.asc(), FAQ.created_at.asc()).all()
        return render_template('admin/faq.html', faqs=faqs)

    @app.route('/admin/faq/<int:faq_id>/edit', methods=['GET'])
    @admin_required
    def admin_faq_edit(faq_id):
        faq = FAQ.query.get_or_404(faq_id)
        return render_template('admin/faq_edit.html', faq=faq)

    @app.route('/admin/faq/<int:faq_id>/delete', methods=['POST'])
    @admin_required
    def admin_faq_delete(faq_id):
        faq = FAQ.query.get_or_404(faq_id)
        db.session.delete(faq)
        db.session.commit()
        flash('FAQ question deleted successfully!')
        return redirect(url_for('admin_faq'))

    # Homepage Section Management Routes
    @app.route('/admin/homepage-sections', methods=['GET', 'POST'])
    @admin_required
    def admin_homepage_sections():
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'update':
                section_id = request.form.get('section_id', type=int)
                title = request.form.get('title', '').strip()
                subtitle = request.form.get('subtitle', '').strip()
                content = request.form.get('content', '').strip()
                
                if section_id:
                    section = HomepageSection.query.get_or_404(section_id)
                    section.title = title
                    section.subtitle = subtitle
                    section.content = content
                    section.updated_at = datetime.utcnow()
                    db.session.commit()
                    flash('Homepage section updated successfully!')
                else:
                    flash('Invalid section ID.', 'error')
            
            elif action == 'toggle':
                section_id = request.form.get('section_id', type=int)
                if section_id:
                    section = HomepageSection.query.get_or_404(section_id)
                    section.is_active = not section.is_active
                    section.updated_at = datetime.utcnow()
                    db.session.commit()
                    status = 'activated' if section.is_active else 'deactivated'
                    flash(f'Homepage section {status} successfully!')
                else:
                    flash('Invalid section ID.', 'error')
            
            return redirect(url_for('admin_homepage_sections'))
        
        # Get all homepage sections ordered by order field
        sections = HomepageSection.query.order_by(HomepageSection.order.asc(), HomepageSection.created_at.asc()).all()
        return render_template('admin/homepage_sections.html', sections=sections)

    @app.route('/admin/homepage-sections/<int:section_id>/edit', methods=['GET'])
    @admin_required
    def admin_homepage_section_edit(section_id):
        section = HomepageSection.query.get_or_404(section_id)
        return render_template('admin/homepage_section_edit.html', section=section)

    @app.context_processor
    def inject_site_settings():
        """Make site settings available in all templates"""
        return dict(site_settings=get_site_settings())

    # Helper injection removed to avoid initialization order issues

    # -----------------------------
    # Payments (Stripe) - Guarded
    # -----------------------------
    def get_stripe_config():
        publishable_key = get_setting('stripe_publishable_key', '')
        secret_key = get_setting('stripe_secret_key', '')
        webhook_secret = get_setting('stripe_webhook_secret', '')
        return publishable_key, secret_key, webhook_secret

    def is_stripe_ready():
        if stripe is None:
            return False
        _, secret_key, _ = get_stripe_config()
        return bool(secret_key)

    @app.route('/create-checkout-session', methods=['POST'])
    def create_checkout_session():
        try:
            # Basic guardrails
            if not is_stripe_ready():
                return jsonify({'error': 'Payments not configured'}), 503

            data = request.get_json(silent=True) or {}
            plan_id = data.get('plan_id')
            billing_cycle = (data.get('billing_cycle') or 'monthly').lower()

            if not plan_id or billing_cycle not in {'monthly', 'yearly'}:
                return jsonify({'error': 'Invalid request'}), 400

            plan = Plan.query.get(plan_id)
            if not plan or not plan.is_active:
                return jsonify({'error': 'Plan not found'}), 404

            # Choose price ID by cycle
            price_id = plan.stripe_monthly_price_id if billing_cycle == 'monthly' else plan.stripe_yearly_price_id
            if not price_id:
                return jsonify({'error': 'Price ID not configured for this plan'}), 400

            # Configure stripe
            _, secret_key, _ = get_stripe_config()
            stripe.api_key = secret_key

            # Build success/cancel URLs
            success_url = url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}'
            cancel_url = url_for('plans', _external=True)

            # Create checkout session (subscription)
            session_args = {
                'mode': 'subscription',
                'payment_method_types': ['card'],
                'line_items': [{'price': price_id, 'quantity': 1}],
                'success_url': success_url,
                'cancel_url': cancel_url,
                'metadata': {
                    'plan_id': str(plan.id),
                    'plan_name': plan.name,
                    'billing_cycle': billing_cycle,
                },
            }
            # Pass customer_email if logged in
            if current_user.is_authenticated:
                session_args['customer_email'] = current_user.email  # type: ignore[attr-defined]

            checkout_session = stripe.checkout.Session.create(**session_args)
            return jsonify({'checkout_url': checkout_session.url})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/payment-success')
    @login_required
    def payment_success():
        # Verify session and upsert subscription, then redirect back to plans
        try:
            if not is_stripe_ready():
                flash('Payment processed, but Stripe is not fully configured.', 'warning')
                return redirect(url_for('plans'))

            session_id = request.args.get('session_id')
            if not session_id:
                return redirect(url_for('plans'))

            _, secret_key, _ = get_stripe_config()
            stripe.api_key = secret_key

            checkout_session = stripe.checkout.Session.retrieve(session_id, expand=['subscription'])
            if not checkout_session:
                return redirect(url_for('plans'))

            # Read plan metadata we set when creating the session
            meta = checkout_session.get('metadata') or {}
            plan_id_str = meta.get('plan_id')
            if plan_id_str and plan_id_str.isdigit():
                plan_id = int(plan_id_str)
                plan = Plan.query.get(plan_id)
                if plan:
                    # Extract Stripe subscription data
                    sub_id = None
                    current_period_end = None
                    sub_obj = checkout_session.get('subscription')
                    if isinstance(sub_obj, dict):
                        sub_id = sub_obj.get('id')
                        ts = sub_obj.get('current_period_end')
                        if ts:
                            try:
                                from datetime import datetime
                                current_period_end = datetime.utcfromtimestamp(int(ts))
                            except Exception:
                                current_period_end = None
                    elif isinstance(sub_obj, str):
                        sub_id = sub_obj

                    # Ensure table exists and clean transaction state
                    try:
                        from sqlalchemy import inspect
                        insp = inspect(db.engine)
                        if not insp.has_table('user_subscription'):
                            db.create_all()
                    except Exception:
                        # Ignore table introspection errors; create_all later if needed
                        pass

                    # Retryable write
                    for attempt in range(2):
                        try:
                            # Clear any failed transaction state
                            try:
                                db.session.rollback()
                            except Exception:
                                pass

                            # Deactivate previous subs via ORM to avoid bulk-update transaction issues
                            prev_subs = UserSubscription.query.filter_by(user_id=current_user.id, status='active').all()
                            for ps in prev_subs:
                                ps.status = 'canceled'

                            new_sub = UserSubscription(
                                user_id=current_user.id,
                                plan_id=plan.id,
                                stripe_subscription_id=sub_id,
                                status='active',
                                current_period_end=current_period_end
                            )
                            db.session.add(new_sub)
                            db.session.commit()
                            break
                        except Exception:
                            db.session.rollback()
                            # Try to create tables and retry once
                            try:
                                db.create_all()
                            except Exception:
                                pass
                            if attempt == 1:
                                raise

            flash('Subscription activated successfully.', 'success')
        except Exception as e:
            flash(f'Payment processed but could not update subscription: {e}', 'warning')
        return redirect(url_for('plans'))

    @app.route('/stripe-webhook', methods=['POST'])
    def stripe_webhook():
        # Gracefully no-op if not configured
        if not is_stripe_ready():
            return ('', 200)

        payload = request.get_data(as_text=True)
        sig_header = request.headers.get('Stripe-Signature', '')
        _, _, webhook_secret = get_stripe_config()

        # If no webhook secret, accept without processing to avoid outages
        if not webhook_secret:
            return ('', 200)

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except Exception:
            return ('', 400)

        # Handle a few key events (logging only for now)
        et = event['type']
        obj = event['data']['object']
        if et == 'checkout.session.completed':
            # Subscription created/paid
            pass
        elif et == 'invoice.payment_succeeded':
            pass
        elif et == 'customer.subscription.deleted':
            pass
        # Extend later with DB updates when subscription model is added

        return ('', 200)

    with app.app_context():
        db.create_all()
        # Create demo chatbot after all services are initialized
        try:
            create_demo_chatbot_internal()
        except Exception as e:
            print(f"[WARNING] Failed to create demo chatbot: {e}")
    
    return app 