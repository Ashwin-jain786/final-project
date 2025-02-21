from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_from_directory
import os

from flask_sqlalchemy import SQLAlchemy
import google.generativeai as genai
from PIL import Image
import io
import base64
import os
import secrets
import sqlite3

from datetime import datetime
import logging

app = Flask(__name__)
app.secret_key = secrets.token_hex(24)

# Configure PDF storage
PDF_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quiz_pdfs')
os.makedirs(PDF_DIRECTORY, exist_ok=True)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def standardize_response(status, message, data=None, status_code=200):
    """Standardize API responses"""
    response = {
        'status': status,
        'message': message
    }
    if data is not None:
        response['data'] = data
    return jsonify(response), status_code

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quiz.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Quiz Result Model
class QuizResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

# Quiz Routes
@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        data = request.json
        level = data.get('level', 'beginner')
        try:
            return jsonify({
                "quiz_html": render_template('quiz.html', level=level)
            })
        except Exception as e:
            logger.error(f"Error loading quiz: {str(e)}")
            return standardize_response('error', 'Failed to load quiz', status_code=500)
            
    level = request.args.get('level', 'beginner')
    try:
        return render_template('quiz.html', level=level)
    except Exception as e:
        logger.error(f"Error loading quiz: {str(e)}")
        return redirect(url_for('dashboard'))

@app.route('/generate_questions', methods=['POST'])
def generate_questions():
    if 'user_id' not in session:
        return standardize_response('error', 'Not authenticated', status_code=401)
        
    try:
        data = request.json
        class_level = data.get('class')
        subject = data.get('subject')
        num_questions = data.get('num_questions', 10)
        
        if not class_level or not subject:
            return standardize_response('error', 'Class and subject are required', status_code=400)
            
        # Generate prompt for Gemini AI
        prompt = f"Generate {num_questions} multiple choice questions for class {class_level} {subject}. "\
                "Each question should have 4 options and indicate the correct answer. "\
                "Format the response as a JSON array where each question has: "\
                "question, options (array), and answer."
                
        # Get response from Gemini AI
        response = model.generate_content(prompt)
        
        try:
            questions = json.loads(response.text)
            return standardize_response('success', 'Questions generated', questions)
        except json.JSONDecodeError:
            return standardize_response('error', 'Failed to parse AI response', status_code=500)
            
    except Exception as e:
        logger.error(f"Error generating questions: {str(e)}")
        return standardize_response('error', 'Failed to generate questions', status_code=500)

@app.route('/quiz/results', methods=['POST'])
def save_result():
    """Save quiz results and generate personalized feedback using Gemini AI"""
    if 'user_id' not in session:
        return standardize_response('error', 'Not authenticated', status_code=401)
        
    try:
        data = request.json
        if not data or 'level' not in data or 'score' not in data or 'total' not in data:
            return standardize_response('error', 'Invalid data format', status_code=400)
            
        # Save quiz result to database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return standardize_response('error', 'User not found', status_code=404)
            
        result = QuizResult(
            username=user['username'],
            level=data['level'],
            score=data['score'],
            total=data['total']
        )
        db.session.add(result)
        db.session.commit()
        
        # Save quiz result to chat history
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO history (user_id, user_message, bot_response) VALUES (?, ?, ?)",
                      (session['user_id'], 
                       f"Completed {data['level']} quiz",
                       f"Score: {data['score']}/{data['total']}"))
        conn.commit()
        conn.close()
        
        return standardize_response('success', 'Result saved successfully', {
            'score': data['score'],
            'total': data['total']
        })
    except Exception as e:
        logger.error(f"Error saving quiz result: {str(e)}")
        return standardize_response('error', 'Internal server error', status_code=500)

# Gemini AI Configuration
GOOGLE_API_KEY = "AIzaSyCaQ8TCqP0cRp4PNcU1XFugHnT8spMTXJA"
os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
# Initialize both text and vision models
text_model = genai.GenerativeModel('gemini-pro')
vision_model = genai.GenerativeModel('gemini-pro-vision')


# Chatbot Database Setup
DATABASE = 'chatbot.db'

def create_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_message TEXT NOT NULL,
            bot_response TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

create_db()

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def get_gemini_response(prompt, history=None):
    if history:
        prompt_with_history = "\n".join(history + [f"User: {prompt}"])
    else:
        prompt_with_history = prompt
    try:
        response = model.generate_content(prompt_with_history)
        return response.text
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return None

# Authentication Routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            conn.close()
            return render_template('register.html', error='Username already exists')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            session['user_id'] = user['id']
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# Main Routes
@app.route("/")
def index():
    if 'user_id' in session:
        return render_template("chatbot.html")
    else:
        return redirect(url_for('login'))

@app.route("/process_image", methods=["POST"])
def process_image():
    if 'user_id' not in session:
        return standardize_response('error', 'Please log in to use the chatbot.')

    if 'image' not in request.files:
        return standardize_response('error', 'No image file provided')

    try:
        # Get the image file
        image_file = request.files['image']
        
        # Convert image to base64
        image_bytes = image_file.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Create PIL Image
        image = Image.open(io.BytesIO(image_bytes))
        
        # Generate response using Gemini Vision
        response = vision_model.generate_content([
            "Analyze this image and provide a detailed description. Answer any questions the user might have about the image.",
            image
        ])
        
        # Save to chat history
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO history (user_id, user_message, bot_response) VALUES (?, ?, ?)",
                      (session['user_id'], "Uploaded image", response.text))
        conn.commit()
        conn.close()
        
        return standardize_response('success', response.text)
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        return standardize_response('error', 'Failed to process image')

@app.route("/get_response", methods=["POST"])

def get_response():
    if 'user_id' not in session:
        return standardize_response('error', 'Please log in to use the chatbot.')

    try:
        user_message = request.form["user_message"]
        user_id = session['user_id']

        # Check if user wants to start a quiz
        if user_message.lower().strip() in ["start quiz", "take quiz", "begin quiz"]:
            return standardize_response('success', 'Choose a quiz level:', {
                'quiz_levels': ["beginner", "intermediate", "advanced"]
            })

        # Check if user selected a quiz level
        if user_message.lower().strip() in ["beginner", "intermediate", "advanced"]:
            level = user_message.lower().strip()
            return standardize_response('success', f'Starting {level} quiz...', {
                'quiz_start': True,
                'level': level
            })

        # Check if message contains image reference
        if user_message.lower().startswith(("what is in this image", "describe this image", "analyze this image")):
            return standardize_response('info', 'Please upload an image first using the image icon.')
            
        gemini_response = text_model.generate_content(user_message).text


        if gemini_response:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO history (user_id, user_message, bot_response) VALUES (?, ?, ?)",
                          (user_id, user_message, gemini_response))
            conn.commit()
            conn.close()
            return standardize_response('success', gemini_response)
        else:
            return standardize_response('error', 'Error getting response from the AI model.')
    except Exception as e:
        logger.error(f"Error in get_response: {str(e)}")
        return standardize_response('error', 'An unexpected error occurred while processing your request.')

@app.route("/profile")
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return redirect(url_for('login'))
        
    return render_template("profile.html", username=user['username'])

@app.route("/schedule")
def schedule():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template("schedule.html")

@app.route("/weaknesses")
def weaknesses():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template("weaknesses.html")

@app.route('/get_quiz_pdf', methods=['POST'])
def get_quiz_pdf():
    """Serve quiz PDF based on class and subject"""
    if 'user_id' not in session:
        return standardize_response('error', 'Not authenticated', status_code=401)
        
    try:
        data = request.json
        class_level = data.get('class')
        subject = data.get('subject')
        
        if not class_level or not subject:
            return standardize_response('error', 'Class and subject are required', status_code=400)
            
        # Construct filename
        filename = f"{class_level}_{subject}.pdf"
        filepath = os.path.join(PDF_DIRECTORY, filename)
        
        if not os.path.exists(filepath):
            return standardize_response('error', 'Quiz not found', status_code=404)
            
        return send_from_directory(PDF_DIRECTORY, filename, as_attachment=True)
        
    except Exception as e:
        logger.error(f"Error serving quiz PDF: {str(e)}")
        return standardize_response('error', 'Failed to serve quiz PDF', status_code=500)

@app.route("/dashboard")

def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template("dashboard.html")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
