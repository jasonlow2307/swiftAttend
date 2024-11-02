import os
from flask import Blueprint, jsonify, render_template, request
from common import *
from functions import get_random_emoji
from wrapper import *
from functions import *
import random
import json

browse = Blueprint('browse', __name__)

load_dotenv()
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')

@browse.route('/courses')
@login_required
def list_classes():
    role = session.get('role')
    print(role)
    if role == "lecturer" or role == "admin":
        courses = fetch_courses_from_dynamodb()
    else:
        courses = fetch_courses_from_dynamodb(student_id=session.get('id'))
    
    for course in courses:
        course['StudentCount'] = len(course['Students'].split('|'))

        course_students = fetch_users_from_dynamodb("students", course['Students'].split('|'))
        course_lecturer = fetch_users_from_dynamodb("lecturers", [course['Lecturer']])[0]
        
        # Convert course lecturer's name to string
        course['Lecturer'] = course_lecturer
        course_lecturer['FullName'] = course_lecturer['FullName']['S']
        
        # Extract LecturerId as string
        lecturer_id = course_lecturer['LecturerId']['S']
        image_key = 'index/' + lecturer_id
        course['Lecturer']['Image'] = generate_signed_url(S3_BUCKET_NAME, image_key)

        students = []
        for item in course_students:
            student = {
                'FullName': item.get('FullName', {}).get('S'),
                'StudentId': item.get('StudentId', {}).get('S')
            }
            students.append(student)

        course['Lecturer'] = course_lecturer
        course['Students'] = students

        for student in course['Students']:
            student_id = student['StudentId']
            image_key = 'index/' + student_id
            student['Image'] = generate_signed_url(S3_BUCKET_NAME, image_key)

        # Default value for all_students
        all_students = fetch_users_from_dynamodb("students")
        for student in all_students:
            student_id = student['StudentId']
            image_key = 'index/' + student_id
            student['Image'] = generate_signed_url(S3_BUCKET_NAME, image_key)

        course_students_ids = [int(student['StudentId']['S']) for student in course_students]
        new_students = []
        for student in all_students:
            for student_id in course_students_ids:
                if student['StudentId'] != str(student_id):
                    new_students.append(student)
    
        course['NewStudents'] = new_students
    
    if role == "lecturer" or role == "admin":
        return render_template('courses_lecturer.html', courses=courses, all_students=all_students)
    else:
        return render_template('courses_student.html', courses=courses)

# For adding students to course
@browse.route('/add_student', methods=['POST'])
def add_student():
    data = request.get_json()
    student_id = data['studentId']
    course_code = data['courseCode']

    print(student_id)

    edit_student_in_course(student_id, course_code, True)
    return jsonify({'success': True, 'message': 'Student added successfully!'}), 200

# For removing students from course
@browse.route('/remove_student', methods=['POST'])
def remove_student():
    data = request.get_json()
    student_id = data['studentId']
    course_code = data['courseCode']

    print(student_id)

    edit_student_in_course(student_id, course_code, False)

    return jsonify({'success': True, 'message': 'Student removed successfully!'}), 200

banners = []

# Profile page
@browse.route('/profile', methods=['GET'])
@login_required
def profile():
    global banners
    profile = fetch_users_from_dynamodb(session.get('role'), [session.get('id')])[0]
    image = generate_signed_url(S3_BUCKET_NAME, 'index/' + session.get('id'))
    profile['FullName'] = profile['FullName']['S']
    profile['BannerImg'] = profile['BannerImg']['S']
    
    # Save RekognitionId to session
    profile['RekognitionId'] = profile['RekognitionId']['S']
    session['RekognitionId'] = profile['RekognitionId']
    print(profile)

    if 'LecturerId' in profile:
        profile['LecturerId'] = profile['LecturerId']['S']
    else:
        profile['StudentId'] = profile['StudentId']['S']
    profile['image'] = image

    # Find classes enrolled in and attendance rate
    if session.get('role') == 'student':
        courses = fetch_courses_from_dynamodb(student_id=session.get('id'))
        for course in courses:
            course['AttendanceRate'] = calculate_attendance_rate(course['CourseCode'], session.get('id'))
            # Setting Lecturer Name
            lecturer = fetch_users_from_dynamodb("lecturer", user_ids=[course['Lecturer']])[0]
            course['Lecturer'] = f"{lecturer['FullName']['S']} ({course['Lecturer']})"

            course['CourseName'] = f"{get_random_emoji()} {course['CourseName']}"

            course['StudentCount'] = course['Students'].count('|') + 1
        print(courses)
    else:
        courses = fetch_courses_from_dynamodb(lecturer_id=session.get('id'))
        for course in courses:
            course['Lecturer'] = f"{profile['FullName']} ({course['Lecturer']})"
            course['StudentCount'] = course['Students'].count('|') + 1
            # Add a random emoji to the course name
            course['CourseName'] = f"{get_random_emoji()} {course['CourseName']}"

    # Load banners
    for filename in os.listdir('static/banners'):
        if filename.endswith('.jpg') or filename.endswith('.png') or filename.endswith('.jpeg'):
            banners.append('static/banners/' + filename)
    
    random_banners = []
    
    for i in range(3):
        random_banner = random.choice(banners)
        if random_banner not in random_banners:
            random_banners.append(random_banner)

    # TODO implement animation for more banners

    return render_template('profile.html', profile=profile, courses=courses, banners=random_banners)

@browse.route('/set_banner', methods=['POST'])
def set_banner():
    student_id = session.get('id')
    selected_banner = request.form['selected_banner']
    
    if session['role'] == "lecturer":
        table_name = DYNAMODB_LECTURER_TABLE_NAME
    else:
        table_name = DYNAMODB_STUDENT_TABLE_NAME

    dynamodb.update_item(
        TableName = table_name,
        Key={'RekognitionId': {'S': session['RekognitionId']}},
        UpdateExpression='SET BannerImg = :val',
        ExpressionAttributeValues={':val': {'S': selected_banner}}
    )
    return jsonify({'status': 'success', 'banner': selected_banner})

@browse.route('/get_more_banners', methods=['POST'])
def get_more_banners():
    global banners 
    current_banners = request.form['current_banners']
    current_banners_list = json.loads(current_banners)
    
    new_banners = [banner for banner in banners if banner not in current_banners_list]

    print("BANNERS", current_banners_list)

    # Ensure new_banners has at least 3 unique objects
    unique_banners = list(set(new_banners))

    random_banners = random.sample(unique_banners, 3)

    print("RANDOM NEW BANNERS", random_banners)
    return jsonify({'banners': random_banners})

@browse.route('/view_profile', methods=['POST'])
def view_profile():
    data = request.get_json()['rekognitionId']
    
    # Split data
    rekognitionId, id = data.split('//')

    # Get profile based on id
    profile = fetch_users_from_dynamodb("students", [id])
    profile[0]['role'] = 'student'

    if len(profile) == 0:
        profile = fetch_users_from_dynamodb("lecturers", [id])
        profile[0]['role'] = 'lecturer'

    # Pre process profile
    image = generate_signed_url(S3_BUCKET_NAME, 'index/' + id)
    profile = profile[0]

    profile['FullName'] = profile['FullName']['S']
    profile['BannerImg'] = profile['BannerImg']['S']
    
    # Save RekognitionId to session
    profile['RekognitionId'] = profile['RekognitionId']['S']
    session['RekognitionId'] = profile['RekognitionId']

    if 'LecturerId' in profile:
        profile['LecturerId'] = profile['LecturerId']['S']
    else:
        profile['StudentId'] = profile['StudentId']['S']
        courses = fetch_courses_from_dynamodb(student_id=id)
        attendance_rates = []
        for course in courses:
            attendance_rate = calculate_attendance_rate(course['CourseCode'], id)
            if attendance_rate == 'NA':
                attendance_rate = 0
            attendance_rates.append(attendance_rate)
        profile['OverallAttendanceRate'] = sum(attendance_rates) / len(attendance_rates) if attendance_rates else 0

    profile['image'] = image

    print(profile)

    return jsonify(profile)

def calculate_attendance_rate(course_code, student_id):
    """Calculate the attendance rate for a specific student in a course."""
    present_counter = 0
    total_records = 0
    attendance_records = retrieve_student_records(course=course_code)
    
    for record in attendance_records:
        if str(record['StudentId']) == student_id:
            total_records += 1
            if record['Attendance'] == 'PRESENT':
                present_counter += 1
                
    if total_records == 0:
        return "NA"
    return round(present_counter / total_records * 100, 2)

    
    





