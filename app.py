from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from bson.objectid import ObjectId
import requests
import json

app = Flask(__name__)

# MongoDB Configuration for local instance
app.config["MONGO_URI"] = "mongodb://localhost:27017/law"  # Use your desired database name

# Initialize PyMongo
mongo = PyMongo(app)

# Flask-Login Configuration
app.secret_key = 'your_secret_key'
login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id  # Store user ID
        self.username = username

    def get_id(self):
        return self.id  # Return user ID

@login_manager.user_loader
def load_user(user_id):
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    return User(str(user['_id']), user['username']) if user else None

# Google API Key
API_KEY = "AIzaSyBvRZrdFqx8JoWVmTBYdAHwGBLG0Itiesg"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={API_KEY}"

def get_palm_response(query):
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": query}]}]}
    response = requests.post(GEMINI_API_URL, json=payload, headers=headers)

    print("Full API Response:", response.text)

    if response.status_code == 200:
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
    else:
        return f"Error: {response.status_code} - {response.text}"

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']  # Handle password securely in a real app

        user = mongo.db.users.find_one({"username": username})
        if user and user['password'] == password:  # In a real app, use hashed passwords
            login_user(User(str(user['_id']), username))
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']  # Handle password securely

        if mongo.db.users.find_one({"username": username}):
            flash("Username already exists.")
        else:
            mongo.db.users.insert_one({"username": username, "password": password})  # Store hashed password
            flash("Registration successful. Please log in.")
            return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    # Retrieve user's chat history
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
    chat = mongo.db.chats.find_one({"_id": ObjectId(chat_id)})
    if chat:
        return jsonify({'messages': chat['messages']})
    return jsonify({'messages': []})  # Return an empty list if chat not found


@app.route('/ask', methods=['POST'])
@login_required
def ask_query():
    user_input = request.form['query']
    chat_id = request.form['chat_id']  # Get the chat_id from the request

    # Retrieve the chat document
    chat = mongo.db.chats.find_one({"_id": ObjectId(chat_id)})

    if chat:
        # Append the user input to the chat messages
        messages = chat.get('messages', [])
        messages.append({'sender': 'user', 'text': user_input})  # Append user message
        mongo.db.chats.update_one({"_id": ObjectId(chat_id)}, {"$set": {"messages": messages}})  # Update chat with new message

        # Create a summary request using the previous messages
        summary_input = "\n".join([msg['text'] for msg in messages if msg['sender'] == 'user'])
        summary_response = get_palm_response(f"Summarize the following chat messages: {summary_input}")

        # Use the summary in the query to the law response
        law_response = get_palm_response(
            f"{summary_response}\n\nUser's latest query: {user_input}. "
            "Please analyze the user's query. If the question is related to genuine legal matters under Indian law, "
            "provide a detailed response citing relevant laws, sections, and possible solutions. If the query is irrelevant, "
            "unrelated to Indian law, or offensive, do not provide any response and ignore the query. "
            "Limit your response to 1000 words."
        )

        # Append the bot response to the chat messages
        messages.append({'sender': 'bot', 'text': law_response})  # Append bot message
        mongo.db.chats.update_one({"_id": ObjectId(chat_id)}, {"$set": {"messages": messages}})  # Update chat with new message

    return jsonify({'response': law_response})



@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
