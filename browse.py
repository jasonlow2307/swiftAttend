from flask import Blueprint, jsonify, render_template, request
from common import *
from config import *
from wrapper import *
from functions import *

browse = Blueprint('browse', __name__)

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