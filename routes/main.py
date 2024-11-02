from flask import Blueprint, jsonify, render_template, request
from common import *
from wrapper import *
from functions import *

main = Blueprint('main', __name__)

load_dotenv()
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
BOT_ID=os.getenv('BOT_ID')
BOT_ALIAS_ID=os.getenv('BOT_ALIAS_ID')
LOCALE_ID=os.getenv('LOCALE_ID')
SESSION_ID=os.getenv('SESSION_ID')

@main.route('/')
@login_required
def index():
    role = session.get('role')
    id = session.get('id')
    print("DASHBOARD LOADED FOR ID: ", id)

    if role == 'student':
        user, courses, rate = get_student_data(id)
    elif role == 'lecturer':
        user, courses, rate = get_lecturer_data(id)
    else:
        user = {'FullName': {'S': "Admin"}}
        courses = []
        rate = 0

    welcome_message = f"Welcome back, {user['FullName']['S']} ({id})"

    if role == 'student':
        return render_template('index_student.html', user=user, courses=courses, rate=rate)
    elif role == 'lecturer':
        return render_template('index_lecturer.html', user=user, courses=courses, rate=rate)
    else:
        return render_template('index_admin.html', welcome_message=welcome_message)

@main.route('/bot')
def bot():
    return render_template('bot.html')

@main.route('/bot_form', methods=['POST'])
def bot_send():
    data = request.json
    user_input = data['message']

    response = lex_client.recognize_text(
        botId=BOT_ID,  
        botAliasId=BOT_ALIAS_ID, 
        localeId=LOCALE_ID,
        sessionId=SESSION_ID,  
        text=user_input
    )

    messages = response.get('messages', [])
    bot_messages = []

    if messages:
        for message in messages:
            bot_message = message.get('content', '')
            bot_messages.append(bot_message)
    else:
        bot_messages.append("Sorry, I didn't understand that.")

    return jsonify({'messages': bot_messages})

