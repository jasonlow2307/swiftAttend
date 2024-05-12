from flask import Blueprint, send_from_directory, request, jsonify, render_template
from datetime import datetime
import io
from config import *
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from common import s3, dynamodb, rekognition
import ast

blueprint = Blueprint('app', __name__)

initialized_date = ''
initialized_course = ''

@blueprint.route('/')
def index():
    return send_from_directory('.', 'pages/index.html')

@blueprint.route('/reg')
def register():
    return send_from_directory('.', 'pages/registration.html')

@blueprint.route('/init')
def initialize():
    courses = fetch_courses_from_dynamodb()
    return render_template('initializeAttendance.html', courses=courses)

@blueprint.route('/check')
def check_attendance():
    return send_from_directory('.', 'pages/checkingAttendance.html')

@blueprint.route('/ret')
def retrieve():
    return send_from_directory('.', 'pages/retrieveAttendance.html')

@blueprint.route('/create')
def create_class():
    students = fetch_students_from_dynamodb()
    for student in students:
        student['StudentId'] = int(student['StudentId'])
    return render_template('createClass.html', students=students)

@blueprint.route('/create_form', methods=['POST'])
def create_class_record():
    course_name = request.form['courseName']
    course_code = request.form['courseCode']
    day = request.form['day']
    time = request.form['time']
    # Getting list of students in string 
    selected_students = request.form.getlist('students')
    # List to store converted students in proper dictionary format
    selected_students_dic = []
    for student in selected_students:
        student = ast.literal_eval(student)
        student['StudentId'] = str(student['StudentId'])
        selected_students_dic.append(student)
    
    # Join all student ids of selected students with | separator
    selected_student_ids = "|".join(student['StudentId'] for student in selected_students_dic)

    item = {
        'CourseCode': {'S': course_code},
        'CourseName': {'S': course_name},
        'Day': {'S': day},
        'Time': {'S': time},
        'Students': {'S': selected_student_ids}
    }
        
    dynamodb.put_item(
        TableName= DYNAMODB_CLASSES_TABLE_NAME,
        Item=item
    )
    
    return jsonify({'success': True, 'message': 'Class created successfully!'}), 200

@blueprint.route('/init_form', methods=['POST'])
def initialize_class_record():
    global initialized_date
    global initialized_course

    date = request.form['date']
    selected_course = request.form['course']
    selected_course = ast.literal_eval(selected_course)

    date_and_time = datetime.strptime(date + ' ' + selected_course['Time'], '%Y-%m-%d %H:%M')
    initialized_date = str(date_and_time)
    initialized_course = selected_course['CourseCode']
                                      

    student_ids = selected_course['Students'].split('|')

    matched_students = fetch_matching_students(student_ids)

    class_record = {
        'Course': selected_course['CourseCode'],
        'StartTime': date_and_time,
        'Students': matched_students
    }
    
    save_class_record(class_record)

    return jsonify({'success': True, 'message': 'Class initialized successfully!'}), 200
    

@blueprint.route('/reg_form', methods=['POST'])
def save_student_registration():
    image = request.files['image']
    name = request.form['name']
    student_id = request.form['studentid']

    bucket_name = 'swift-attend-faces'
    key = f'index/{student_id}'
    image_bytes = image.read()
    s3.upload_fileobj(
        io.BytesIO(image_bytes),
        bucket_name,
        key,
        ExtraArgs={'Metadata': {'FullName': name, 'student_id': student_id}}
    )

    return '', 200

@blueprint.route('/check_form', methods=['POST'])
def check_attendance_record():
    global initialized_course
    global initialized_date

    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    image_file = request.files['image']
    image_bytes = image_file.read()

    response_index = rekognition.index_faces(
        CollectionId=REKOGNITION_COLLECTION_NAME,
        Image={'Bytes': image_bytes}
    )

    face_ids = [face['Face']['FaceId'] for face in response_index.get('FaceRecords', [])]
    
    detected_student_id = set()

    for face_id in face_ids:
        response_search = rekognition.search_faces(
            CollectionId=REKOGNITION_COLLECTION_NAME,
            FaceId=face_id, 
            FaceMatchThreshold=70,
            MaxFaces=10
        )

        if 'FaceMatches' in response_search and len(response_search['FaceMatches']) > 0:
                for match in response_search['FaceMatches']:
                    person_info = dynamodb.get_item(
                        TableName=DYNAMODB_REGISTRATION_TABLE_NAME,
                        Key={'RekognitionId': {'S': match['Face']['FaceId']}}
                    )
                    if 'Item' in person_info:
                        detected_student_id.add(person_info['Item']['StudentId']['S'])

    student_records = fetch_student_records()

    attendance_records = []

    for student in student_records:
        attendance_status = 'PRESENT' if student['StudentId'] in detected_student_id else 'ABSENT'
        image_key = 'index/' + student['StudentId']
        signed_url = generate_signed_url('swift-attend-faces', image_key)
        attendance_records.append({'FullName': student['FullName'], 'Attendance': attendance_status, 'SignedURL': signed_url})
        update_attendance(student['StudentId'], attendance_status, initialized_date)

    return render_template('checked_attendance.html', attendance_records=attendance_records)

@blueprint.route('/ret_form', methods=['POST'])
def retrieve_attendance_records():
    course = request.form.get('course')
    date = request.form.get('date')
    time = request.form.get('time')

    if date and not time:
        return render_template('error.html', message='Time is required when date is provided.')

    student_records = retrieve_student_records(course, date, time)

    if not student_records:
        return render_template('error.html', message='No records found.')

    return render_template('attendance_records.html', attendance_records=student_records)

############################ Custom Functions ###########################
# For /init
# Fetch all classes from the classes table
def fetch_courses_from_dynamodb():
    response = dynamodb.scan(
        TableName= DYNAMODB_CLASSES_TABLE_NAME
    )
    items = response.get('Items', [])
    courses = []
    for item in items:
        course = {
            'CourseCode': item.get('CourseCode', {}).get('S'),
            'CourseName': item.get('CourseName', {}).get('S'),
            'Day': item.get('Day', {}).get('S'),
            'Time': item.get('Time', {}).get('S'),
            'Students': item.get('Students', {}).get('S')
        }
        courses.append(course)
    return courses

# For /init_form
# Return students with matching IDs for the selected course
def fetch_matching_students(student_ids):
    students = []
    for student_id in student_ids:
        response = dynamodb.scan(
            TableName=DYNAMODB_REGISTRATION_TABLE_NAME,
            FilterExpression='StudentId = :student_id',
            ExpressionAttributeValues={':student_id': {'S': student_id}}
        )
        items = response.get('Items', [])
        students.extend(items)
    return students

# For /create and /create_form
# Return all students from registration table
def fetch_students_from_dynamodb():
    response = dynamodb.scan(
        TableName= DYNAMODB_REGISTRATION_TABLE_NAME
    )
    items = response.get('Items', [])
    students = []
    for item in items:
        student = {
            'FullName': item.get('FullName', {}).get('S'),
            'StudentId': item.get('StudentId', {}).get('S')
        }
        students.append(student)
    return students

# For /create_form
# Save created class record to DynamoDB
def create_class_record(course_code, course_name, day, time, selected_students):
    selected_student_ids = ""

    for student in selected_students:
        selected_student_ids = selected_student_ids + "|" + student['StudentId']

    item = {
        'CourseCode': {'S': course_code},
        'CourseName': {'S': course_name},
        'Day': {'S': day},
        'Time': {'S': time},
        'Students': {'S': selected_student_ids}
    }
        
    dynamodb.put_item(
        TableName= DYNAMODB_CLASSES_TABLE_NAME,
        Item=item
    )
    return {'success': True, 'message': 'Class created successfully!'}, 200


# For /init_form
# Save initialized class record to DynamoDB
def save_class_record(class_record):
    course = class_record['Course']
    students = class_record['Students']
    
    for student in students:
        item = {
            'Date': {'S': str(class_record['StartTime'])},
            'Course': {'S': course},
            'FullName': student['FullName'],
            'StudentId': student['StudentId'],
            'Attendance': {'S': ''}
        }
        
        dynamodb.put_item(
            TableName= DYNAMODB_ATTENDANCE_TABLE_NAME,
            Item=item
        )

# For /check_form
# Fetch student records based on the initialized date and course
def fetch_student_records():
    global initialized_date
    global initialized_course

    response = dynamodb.scan(
        TableName=DYNAMODB_ATTENDANCE_TABLE_NAME,
        ExpressionAttributeNames={'#D': 'Date'},
        FilterExpression='#D = :d AND Course = :c',
        ExpressionAttributeValues={':d': {'S': initialized_date}, ':c': {'S': initialized_course}}
    )
    items = response.get('Items', [])
    students = []
    for item in items:
        student = {
            'FullName': item.get('FullName', {}).get('S'),
            'StudentId': item.get('StudentId', {}).get('S')
        }
        students.append(student)
    return students

# For /check_form
# Update attendance record in the DynamoDB table
def update_attendance(student_id, attendance, date):
    response = dynamodb.update_item(
        TableName=DYNAMODB_ATTENDANCE_TABLE_NAME,
        Key={
            'StudentId': {'S': student_id},
            'Date': {'S': date}
        },
        UpdateExpression='SET Attendance = :attendance',
        ExpressionAttributeValues={
            ':attendance': {'S': attendance}
        },
        ReturnValues='UPDATED_NEW'
    )
    
# For /ret_form
# Retrieve attendance records based on provided parameters
def retrieve_student_records(course=None, date=None, time=None):
    expression_attribute_names = {}
    expression_attribute_values = {}

    filter_expression_parts = []

    if course:
        expression_attribute_names['#C'] = 'Course'
        expression_attribute_values[':c'] = {'S': course}
        filter_expression_parts.append('#C = :c')

    if date:
        expression_attribute_names['#D'] = 'Date'
        date_str = str(date)
        expression_attribute_values[':d'] = {'S': date_str}
        filter_expression_parts.append('begins_with(#D, :d)')

    if time:
        expression_attribute_names['#T'] = 'Time'
        expression_attribute_values[':t'] = {'S': time}
        filter_expression_parts.append('begins_with(#T, :t)')

    filter_expression = ' AND '.join(filter_expression_parts)

    response = dynamodb.scan(
        TableName=DYNAMODB_ATTENDANCE_TABLE_NAME,
        FilterExpression=filter_expression,
        ExpressionAttributeNames=expression_attribute_names,
        ExpressionAttributeValues=expression_attribute_values
    )

    items = response.get('Items', [])
    students = []
    for item in items:
        student = {
            'FullName': item.get('FullName', {}).get('S'),
            'StudentId': int(item.get('StudentId', {}).get('S')),
            'Date': item.get('Date', {}).get('S'),
            'Attendance': item.get('Attendance', {}).get('S'),
            'Course': item.get('Course', {}).get('S')
        }
        students.append(student)

    return students

# For /check_form and /ret_form
# Generate a presigned URL for an image in the S3 bucket
def generate_signed_url(bucket_name, object_key, expiration=3600):
    try:
        response = s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': object_key},
                                                    ExpiresIn=expiration)
        return response
    except ClientError as e:
        print('Error generating presigned URL:', e)
        return None
