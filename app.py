from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
from googletrans import Translator
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
import spacy
import stripe
import logging
from logging.handlers import RotatingFileHandler
import os
import io
import speech_recognition as sr
import random
from textblob import TextBlob
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import warnings
import secrets
import asyncio

app = Flask(__name__)

# Configuration
app.secret_key = secrets.token_urlsafe(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)
warnings.filterwarnings("ignore")

# Define User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

# Create database
with app.app_context():
    db.create_all()

# Configure logging
handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=1)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

# Load environment variables
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# Load models and pipelines once at startup
nlp = spacy.load("en_core_web_sm")
summarizer = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
model_name = 'facebook/bart-large-mnli'
model = AutoModelForSequenceClassification.from_pretrained(model_name)
tokenizer = AutoTokenizer.from_pretrained(model_name)
classifier = pipeline('zero-shot-classification', model=model, tokenizer=tokenizer)
translator = Translator()

# In-memory user data
user_contexts = {}
user_languages = {}

# Intent classification labels
INTENTS = ["book", "payment", "greeting", "show_options", "help", "cancel_booking", "museum_info"]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sign_up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        hashed_password = generate_password_hash(password, method='sha256')

        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('Account created successfully!')
        return redirect(url_for('sign_in'))

    return render_template('sign_up.html')

@app.route('/sign_in', methods=['GET', 'POST'])
def sign_in():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash('Sign in successful!')
            return redirect(url_for('chatbot'))
        else:
            flash('Invalid email or password')

    return render_template('sign_in.html')

@app.route('/select_language', methods=['POST'])
def select_language():
    try:
        data = request.json
        user_id = data.get('user_id')
        selected_language = data.get('language')

        supported_languages = ["en", "hi", "fr", "es", "ru", "de", "zh", "ja", "ko", "ar", "pt", "it", "tr", "pl", "nl", "sv", "no", "da", "fi"]

        if selected_language not in supported_languages:
            return jsonify({'error': 'Unsupported language'}), 400

        user_languages[user_id] = selected_language
        return jsonify({'status': 'success', 'message': f'Language set to {selected_language}'})
    except Exception as e:
        app.logger.error(f'Error in /select_language: {str(e)}')
        return jsonify({'error': 'Failed to set language. Please try again later.'}), 500

@app.route('/sentiment', methods=['POST'])
def sentiment():
    try:
        data = request.json
        text = data.get('text', '')
        result = analyze_sentiment(text)
        return jsonify({'sentiment': result})
    except Exception as e:
        app.logger.error(f'Error in /sentiment: {str(e)}')
        return jsonify({'error': 'Failed to analyze sentiment. Please try again later.'}), 500

@app.route('/entities', methods=['POST'])
def entities():
    try:
        data = request.json
        text = data.get('text', '')
        result = extract_entities(text)
        return jsonify({'entities': result})
    except Exception as e:
        app.logger.error(f'Error in /entities: {str(e)}')
        return jsonify({'error': 'Failed to extract entities. Please try again later.'}), 500

@app.route('/summarize', methods=['POST'])
def summarize():
    try:
        data = request.json
        text = data.get('text', '')
        result = summarize_text(text)
        return jsonify({'summary': result})
    except Exception as e:
        app.logger.error(f'Error in /summarize: {str(e)}')
        return jsonify({'error': 'Failed to summarize text. Please try again later.'}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        req = request.get_json(force=True)
        user_id = req.get('user_id', 'default_user')
        user_input = req.get('queryInput', {}).get('text', {}).get('text', '')
        user_language = user_languages.get(user_id, 'en')

        context = user_contexts.get(user_id, {})
        response, context = handle_nlp_intent(user_input, context)
        user_contexts[user_id] = context

        translated_response = translator.translate(response, dest=user_language).text
        return jsonify({'fulfillmentText': translated_response})
    except Exception as e:
        app.logger.error(f'Error in /webhook: {str(e)}')
        return jsonify({'error': 'An internal error occurred. Please try again later.'}), 500

@app.route('/create-payment-intent', methods=['POST'])
def create_payment_intent():
    try:
        data = request.json
        amount = data.get('amount')  # Amount in cents
        if not isinstance(amount, int) or amount <= 0:
            return jsonify({'error': 'Invalid amount'}), 400
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency='usd',
            payment_method_types=['card'],
        )
        return jsonify({'clientSecret': intent.client_secret})
    except Exception as e:
        app.logger.error(f'Error in /create-payment-intent: {str(e)}')
        return jsonify({'error': 'Failed to create payment intent. Please try again later.'}), 500

@app.route('/confirm_payment', methods=['POST'])
def confirm_payment():
    try:
        data = request.json
        payment_method_id = data.get('payment_method_id')
        if not payment_method_id:
            return jsonify({'error': 'Payment method ID required'}), 400
        intent = stripe.PaymentIntent.confirm(payment_method_id)
        if intent.status == 'succeeded':
            return jsonify({'message': 'Payment successful'}), 200
        else:
            return jsonify({'message': 'Payment failed'}), 400
    except Exception as e:
        app.logger.error(f'Error in /confirm_payment: {str(e)}')
        return jsonify({'error': 'Failed to confirm payment. Please try again later.'}), 500

@app.route('/voice-chat', methods=['POST'])
def voice_chat():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    try:
        audio_data = file.read()

        # Convert audio to text
        recognizer = sr.Recognizer()
        audio_io = io.BytesIO(audio_data)
        with sr.AudioFile(audio_io) as source:
            audio_listened = recognizer.record(source)
        text = recognizer.recognize_google(audio_listened)

        # For this example, just echo the text back as an audio response
        response_text = f"Echo: {text}"
        response_audio = text_to_speech(response_text)  # Function to convert text to speech

        return send_file(io.BytesIO(response_audio), mimetype='audio/wav', as_attachment=True, download_name='response.wav')
    except Exception as e:
        app.logger.error(f'Error in /voice-chat: {str(e)}')
        return jsonify({'error': 'Failed to process voice chat. Please try again later.'}), 500

def analyze_sentiment(text):
    blob = TextBlob(text)
    sentiment = blob.sentiment.polarity
    if sentiment > 0:
        return 'positive'
    elif sentiment < 0:
        return 'negative'
    else:
        return 'neutral'

def extract_entities(text):
    doc = nlp(text)
    return {ent.label_: ent.text for ent in doc.ents}

def summarize_text(text):
    summary = summarizer(text, max_length=150, min_length=30, do_sample=False)
    return summary[0]['summary_text']

def handle_nlp_intent(user_input, context):
    # Example implementation of intent classification and response handling
    intent = classifier(user_input, INTENTS)
    top_intent = intent['labels'][0]

    responses = {
        'greeting': "Hello! How can I help you today?",
        'book': "You want to book something. Could you please provide more details?",
        'payment': "Let's proceed with the payment. Please provide your payment details.",
        'show_options': "Here are the options available: ...",
        'help': "How can I assist you?",
        'cancel_booking': "Your booking has been cancelled.",
        'museum_info': "The museum is open from 9 AM to 5 PM daily."
    }

    response = responses.get(top_intent, "I'm not sure how to help with that.")
    context['last_intent'] = top_intent
    return response, context

def text_to_speech(text):
    from gtts import gTTS
    tts = gTTS(text)
    audio_file = io.BytesIO()
    tts.write_to_fp(audio_file)
    audio_file.seek(0)
    return audio_file.read()

if __name__ == '__main__':
    app.run(debug=False, threaded=True)
