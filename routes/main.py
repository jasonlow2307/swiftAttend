from flask import Blueprint, jsonify, render_template, request
from common import *
from config import *
from wrapper import *
from functions import *

main = Blueprint('main', __name__)

@main.route('/')
@login_required
def index():
    role = session.get('role')
    id = session.get('id')
    if role == 'student':
        user = fetch_users_from_dynamodb("students", [id])[0]
        user['Image'] = generate_signed_url(S3_BUCKET_NAME, 'index/' + id)
        courses = fetch_courses_from_dynamodb(student_id=id)
        for course in courses:
            present_counter = 0
            total_records = 0
            attendance_records = retrieve_student_records(course=course['CourseCode'])
            if len(attendance_records) != 0:
                for record in attendance_records:
                    if str(record['StudentId']) == id:
                        total_records += 1
                        if record['Attendance'] == 'PRESENT':
                            present_counter += 1
                if total_records != 0:
                    attendance_rate = round(present_counter / total_records * 100, 2)
                else:
                    attendance_rate = 0
                course['AttendanceRate'] = attendance_rate
            else:
                course['AttendanceRate'] = "NA"
            courseCodes = [course['CourseCode'] for course in courses]

            attendance = []

            for course in courseCodes:
                records = retrieve_student_records(course=course)
                for record in records:
                    if str(record['StudentId']) == id:
                        attendance.append(record)
            
            rate = calculate_monthly_attendance(attendance)
    elif role == 'lecturer':
        user = fetch_users_from_dynamodb("lecturers", [id])[0]
        courses = fetch_courses_from_dynamodb(lecturer_id=id)
        for course in courses:
            present_counter = 0
            attendance_records = retrieve_student_records(course=course['CourseCode'])
            course['StudentCount'] = course['Students'].count('|') + 1
            if len(attendance_records) != 0:
                for record in attendance_records:
                    if record['Attendance'] == 'PRESENT':
                        present_counter += 1
                attendance_rate = round(present_counter / len(attendance_records) * 100, 2)
                course['AttendanceRate'] = attendance_rate
        courseCodes = [course['CourseCode'] for course in courses]

        attendance = []

        for course in courseCodes:
            attendance.append(retrieve_student_records(course=course))
    
        rate = calculate_monthly_attendance(attendance[0])
    else:
        user = {'FullName': {'S': "Admin"}}

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
        botId='3KIS3PKPUN',  # Replace with your bot ID
        botAliasId='TSTALIASID',  # Replace with your bot alias
        localeId='en_US',
        sessionId='test',  # Use a unique session ID
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

