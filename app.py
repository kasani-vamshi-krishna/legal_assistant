from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from bson.errors import InvalidId
import requests
import json

app = Flask(__name__)

# MongoDB Configuration
app.config["MONGO_URI"] = "mongodb://localhost:27017/law"
mongo = PyMongo(app)

# Flask-Login Configuration
app.secret_key = 'your_secret_key'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Redirect to login if not authenticated

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

    def get_id(self):
        return self.id

@login_manager.user_loader
def load_user(user_id):
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    return User(str(user['_id']), user['username']) if user else None

# Google API Key and URL
API_KEY = "AIzaSyBmDdsA8u_ApQ3TJCy-0UDr4sS_gRMJwGg"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={API_KEY}"

# Gemini API Call
def get_palm_response(query):
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": query}]}]}
    response = requests.post(GEMINI_API_URL, json=payload, headers=headers)

    print("Full API Response:", response.text)

    if response.status_code == 429:
        return "Rate limit exceeded. Please try again later."
    elif response.status_code != 200:
        return f"Error: {response.status_code} - {response.text}"

    try:
        json_response = response.json()
        if 'candidates' in json_response:
            content = json_response['candidates'][0].get('content', {})
            parts = content.get('parts', [])
            if parts and 'text' in parts[0]:
                return parts[0]['text']
        return "No valid response from PaLM API."
    except json.JSONDecodeError:
        return "Error parsing the response JSON."

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = mongo.db.users.find_one({"username": username})
        if user and check_password_hash(user['password'], password):
            login_user(User(str(user['_id']), username))
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if mongo.db.users.find_one({"username": username}):
            flash("Username already exists.")
        else:
            hashed_pw = generate_password_hash(password)
            mongo.db.users.insert_one({"username": username, "password": hashed_pw})
            flash("Registration successful. Please log in.")
            return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    chats = mongo.db.chats.find({"username": current_user.username})
    return render_template('dashboard.html', username=current_user.username, chats=chats)

@app.route('/new_chat', methods=['POST'])
@login_required
def new_chat():
    chat_id = mongo.db.chats.insert_one({"username": current_user.username, "messages": []}).inserted_id
    return jsonify({'chat_id': str(chat_id)})

@app.route('/get_chat/<chat_id>', methods=['GET'])
@login_required
def get_chat(chat_id):
    try:
        chat = mongo.db.chats.find_one({"_id": ObjectId(chat_id)})
        if chat:
            return jsonify({'messages': chat['messages']})
    except InvalidId:
        return jsonify({'messages': [], 'error': 'Invalid chat ID'}), 400
    return jsonify({'messages': []})

@app.route('/ask', methods=['POST'])
@login_required
def ask_query():
    user_input = request.form.get('query')
    chat_id = request.form.get('chat_id')

    if not user_input or not chat_id:
        return jsonify({'error': 'Missing required data'}), 400

    try:
        chat = mongo.db.chats.find_one({"_id": ObjectId(chat_id)})
    except InvalidId:
        return jsonify({'error': 'Invalid chat ID'}), 400

    if not chat:
        return jsonify({'error': 'Chat not found'}), 404

    # Append user message
    messages = chat.get('messages', [])
    messages.append({'sender': 'user', 'text': user_input})
    mongo.db.chats.update_one({"_id": ObjectId(chat_id)}, {"$set": {"messages": messages}})

    # Generate summary from chat history
    summary_input = "\n".join([msg['text'] for msg in messages if msg['sender'] == 'user'])
    summary_response = get_palm_response(f"Summarize the following chat messages: {summary_input}")

    # Generate legal response
    law_response = get_palm_response(
f'''You are an AI assistant specializing in providing general information and explanations about Indian law. Your purpose is to help users understand legal concepts, relevant laws, and general procedures under the Indian legal system based on their queries.

Input:
- Conversation Summary: {summary_response} (Use this for context, but focus primarily on the latest query)
- User Query: {user_input}

Instructions:

1. **Analyze the User Query:** Carefully read the user's latest query and the conversation summary to understand the legal topic or question being raised.
2. **Determine Relevance and Appropriateness:**
 * Check if the query pertains to genuine legal matters under *Indian law*.
 * Check if the query is non-offensive and within the scope of providing general legal information.
 * **CRITICAL:** You CANNOT provide personalized legal advice, interpret specific case facts, recommend a specific course of action for the user's unique situation, or act as a substitute for a qualified lawyer.
3. **Formulate Response:**
 * **If the query is a valid request for general information about Indian law:**
 * Acknowledge the user's query.
 * Provide a detailed and informative explanation of the relevant legal principles, concepts, and applicable provisions of Indian law.
 * Cite relevant Acts, Sections, or Rules where appropriate to support the explanation (e.g., "As per Section X of the [Specific Act]...", "Under Rule Y of the...").
 * Discuss potential legal avenues, processes, or remedies *in general terms as described by the law*, but *do not* advise the user on what they should do in their specific situation.
 * Maintain a neutral, objective, and informative tone.
 * Include a clear and prominent disclaimer stating that the information provided is for general knowledge only and does not constitute legal advice. Advise the user to consult a qualified legal professional for advice tailored to their specific circumstances.
 * **If the query is irrelevant, unrelated to Indian law, asks for personal legal advice, interprets specific case facts, is offensive, or otherwise outside your scope (INCLUDING simple greetings or small talk):**
* Provide a very brief, polite, and standard response acknowledging you can only help with Indian law.
 * For simple greetings or small talk, a minimal acknowledgement followed by stating your purpose is sufficient (e.g., "Hello! I provide information on Indian law.").
 * For other non-legal or out-of-scope queries, politely state that you can only provide general information about Indian law and cannot assist with that specific type of request (e.g., "I can only provide general information about Indian law, I cannot give personal advice," or "My expertise is in Indian law, I cannot help with that.").
  * **CRITICAL:** In these irrelevant/out-of-scope cases, keep the response extremely short and concise. DO NOT provide a lengthy explanation of why you cannot answer, and DO NOT include the full detailed legal disclaimer. Your response for these types of queries should ideally be just one or two short sentences.
4.  **Constraints:**
   * Limit the total response length to approximately 1000 words for valid legal queries. For irrelevant/out-of-scope queries, the response must be significantly shorter (as described above).
   * Ensure all legal terms and concepts are explained accurately within the context of Indian law (when applicable).
   * DO NOT speculate or provide information you are not confident about.

Your response should follow these instructions precisely based on the user's query.
'''
   )

    # Append bot response
    messages.append({'sender': 'bot', 'text': law_response})
    mongo.db.chats.update_one({"_id": ObjectId(chat_id)}, {"$set": {"messages": messages}})

    return jsonify({'response': law_response})

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
