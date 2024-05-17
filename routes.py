from functools import wraps
import re
from flask import Blueprint, redirect, render_template_string, send_from_directory, request, jsonify, render_template, url_for, session
from datetime import datetime
import io
from config import *
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from common import *
import ast
import random
from datetime import datetime
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email

blueprint = Blueprint('app', __name__)

initialized_date = ''
initialized_course = ''
initialized = False

@blueprint.route('/remove_student', methods=['POST'])
def remove_student():
    data = request.get_json()
    student_id = data['studentId']
    course_code = data['courseCode'].split(': ')[1]

    print(student_id)
    print(course_code)

    remove_student_from_course(student_id, course_code)

    return jsonify({'success': True, 'message': 'Student removed successfully!'}), 200

def remove_student_from_course(student_id, course_code):
    # Can optimize by overloading the function to accept course_code
    courses = fetch_courses_from_dynamodb()
    for course in courses:
        if (course['CourseCode'] == course_code):
            matched_course = course
    
    print(matched_course['Students'])
    matched_course['Students'] = re.sub(r'\|' + re.escape(student_id), '', matched_course['Students'])
    update_classes_table(course_code, matched_course['CourseName'], matched_course['Students'])
    print(str(student_id) + " removed")
    print(matched_course['Students'])

def update_classes_table(course_code, course_name, students):

    dynamodb.update_item(
        TableName=DYNAMODB_CLASSES_TABLE_NAME,
        Key={'CourseCode': {'S': course_code}, 'CourseName': {'S': course_name}},
        UpdateExpression='SET Students = :students',
        ExpressionAttributeValues={':students': {'S': students}},
        ReturnValues='UPDATED_NEW'  # You can specify the desired return values as needed
    )

    return {'success': True, 'message': f'Students updated for course {course_code} successfully!'}, 200



class RegisterForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    given_name = StringField('Given Name', validators=[DataRequired()])
    family_name = StringField('Family Name', validators=[DataRequired()])
    submit = SubmitField('Register')

class ConfirmForm(FlaskForm):
    code = StringField('Confirmation Code:', validators=[DataRequired()])
    submit = SubmitField('Confirm')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

@blueprint.route('/logout', methods=['GET', 'POST'])
def logout():
    print("Session before clearing: ", session)
    session.pop('id_token', None)
    print("Session after clearing: ", session)
    return redirect(url_for('app.login'))

@blueprint.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data
        given_name = form.given_name.data
        family_name = form.family_name.data
        try:
            response = cognito.sign_up(
                ClientId=COGNITO_CLIENT_ID,
                Username=email,
                Password=password,
                UserAttributes=[
                    {
                        'Name': 'given_name',
                        'Value': given_name
                    },
                    {
                        'Name': 'family_name',
                        'Value': family_name
                    }
                ]
            )
            # Save the user's email in the session
            session['email'] = email
            return redirect(url_for('app.confirm'))
        except ClientError as e:
            error = e.response['Error']['Message']
            if e.response['Error']['Code'] == 'UsernameExistsException':
                error = 'This email is already registered. Please log in.'
            return render_template('register.html', form=form, error=error)
    return render_template('register.html', form=form)

@blueprint.route('/confirm', methods=['GET', 'POST'])
def confirm():
    form = ConfirmForm()
    email = session.get('email')
    print("Email")
    print(email)
    if form.validate_on_submit():
        # Retrieve the user's email from the session
        confirmation_code = form.code.data
        try:
            response = cognito.confirm_sign_up(
                ClientId=COGNITO_CLIENT_ID,
                Username=email,
                ConfirmationCode=confirmation_code,
            )
            return redirect(url_for('app.login'))
        except ClientError as e:
            error = e.response['Error']['Message']
            return render_template('confirm.html', form=form, error=error)
    return render_template('confirm.html', form=form)

@blueprint.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data
        try:
            response = cognito.initiate_auth(
                ClientId=COGNITO_CLIENT_ID,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters={
                    'USERNAME': email,
                    'PASSWORD': password,
                }
            )
            if 'AuthenticationResult' in response:
                session['id_token'] = response['AuthenticationResult']['IdToken']
                return redirect(url_for('app.index'))
            else:
                error = response.get('ChallengeName', 'Authentication failed. Please check your email and password.')
                return render_template('login.html', form=form, error=error)
        except ClientError as e:
            error = e.response['Error']['Message']
            return render_template('login.html', form=form, error=error)
    return render_template('login.html', form=form)

# Define login_required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id_token' not in session:
            return render_template_string('''
                <script>
                    alert("You need to log in first.");
                    window.location.href = "{{ url_for('app.login') }}";
                </script>
            ''')
        return f(*args, **kwargs)
    return decorated_function

@blueprint.route('/')
@login_required
def index():
    return send_from_directory('.', 'pages/index.html')

@blueprint.route('/courses')
@login_required
def list_classes():
    courses = fetch_courses_from_dynamodb()
    for course in courses:
        course['StudentCount'] = len(course['Students'].split('|'))

        course_students = fetch_students_from_dynamodb(course['Students'].split('|'))
        students = []

        for item in course_students:
            student = {
                'FullName': item.get('FullName', {}).get('S'),
                'StudentId': item.get('StudentId', {}).get('S')
            }
            students.append(student)

        course['Students'] = students

        for student in course['Students']:
            image_key = 'index/' + str(student['StudentId'])
            student['Image'] = generate_signed_url(S3_BUCKET_NAME, image_key)

        all_students = fetch_students_from_dynamodb()
        course_students_ids = [student['StudentId'] for student in course_students]
        new_students = [student for student in all_students if student['StudentId'] not in course_students_ids]

    return render_template('courses.html', courses=courses, new_students=new_students)

@blueprint.route('/regstd')
@login_required
def registerStd():
    return send_from_directory('.', 'pages/registerStudent.html')

@blueprint.route('/init')
@login_required
def initialize():
    courses = fetch_courses_from_dynamodb()
    return render_template('initializeAttendance.html', courses=courses)

@blueprint.route('/check')
@login_required
def check_attendance():
    global initialized

    if not initialized:
        return render_template_string('''
                <script>
                    alert("You need to initialize the class first.");
                    window.location.href = "{{ url_for('app.initialize') }}";
                </script>
            ''')

    return send_from_directory('.', 'pages/checkingAttendance.html')

@blueprint.route('/ret')
@login_required
def retrieve():
    courses = fetch_courses_from_dynamodb()
    return render_template('retrieveAttendance.html', courses=courses)

@blueprint.route('/create')
@login_required
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
    global initialized

    date = request.form['date']
    selected_course = request.form['course']
    selected_course = ast.literal_eval(selected_course)

    date_and_time = datetime.strptime(date + ' ' + selected_course['Time'], '%Y-%m-%d %H:%M')
    initialized_date = str(date_and_time)
    initialized_course = selected_course['CourseCode']
    initialized = True                           

    student_ids = selected_course['Students'].split('|')

    matched_students = fetch_students_from_dynamodb(student_ids)

    class_record = {
        'Course': selected_course['CourseCode'],
        'StartTime': date_and_time,
        'Students': matched_students
    }
    
    save_class_record(class_record)

    return jsonify({'success': True, 'message': 'Class initialized successfully!'}), 200

    
@blueprint.route('/regstd_form', methods=['POST'])
def save_student_registration():
    image = request.files['image']
    name = request.form['name']

    # Generate student ID
    year_month = datetime.now().strftime('%y%m')
    random_numbers = str(random.randint(1000, 9999))
    student_id = year_month + random_numbers

    # Check if student_id already exists in DYNAMODB_REGISTRATION_TABLE_NAME
    response = dynamodb.scan(
        TableName=DYNAMODB_REGISTRATION_TABLE_NAME,
        FilterExpression='studentId = :student_id',
        ExpressionAttributeValues={':student_id': {'S': student_id}}
    )
    items = response.get('Items', [])
    while items:
        # Regenerate student_id
        random_numbers = str(random.randint(100000, 999999))
        student_id = year_month + random_numbers
        response = dynamodb.scan(
            TableName=DYNAMODB_REGISTRATION_TABLE_NAME,
            FilterExpression='studentId = :student_id',
            ExpressionAttributeValues={':student_id': {'S': student_id}}
        )
        items = response.get('Items', [])

    # Use the generated student ID in your code
    bucket_name = S3_BUCKET_NAME
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
    global initialized

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
    present_counter = 0

    for student in student_records:
        attendance_status = 'PRESENT' if student['StudentId'] in detected_student_id else 'ABSENT'
        if attendance_status == 'PRESENT':
            present_counter += 1
        image_key = 'index/' + student['StudentId']
        signed_url = generate_signed_url(S3_BUCKET_NAME, image_key)
        attendance_records.append({'FullName': student['FullName'], 'Attendance': attendance_status, 'SignedURL': signed_url})
        update_attendance(student['StudentId'], attendance_status, initialized_date)

    if present_counter == 0:
        error = "The people in the image are not in the course, please check if the image is correct"
    else:
        error = ""

    # Reset initialized global variable
    initialized = False

    return render_template('checked_attendance.html', attendance_records=attendance_records, error=error)

@blueprint.route('/ret_form', methods=['POST'])
def retrieve_attendance_records():
    course = ast.literal_eval(request.form.get('course'))
    # Extract the course code from the course string
    course = course ['CourseCode']
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

# For /create and /create_form
# Return all students from registration table
def fetch_students_from_dynamodb(studentIds = None):
    response = dynamodb.scan(
        TableName= DYNAMODB_REGISTRATION_TABLE_NAME
    )
    items = response.get('Items', [])
    students = []
    if (studentIds == None):
        for item in items:
            student = {
                'FullName': item.get('FullName', {}).get('S'),
                'StudentId': item.get('StudentId', {}).get('S')
            }
            students.append(student)
    else:
        # If studentIds provided, filter the items based on those IDs
        for student_id in studentIds:
            response = dynamodb.scan(
                TableName=DYNAMODB_REGISTRATION_TABLE_NAME,
                FilterExpression='StudentId = :student_id',
                ExpressionAttributeValues={':student_id': {'S': student_id}}
            )
            items = response.get('Items', [])
            students.extend(items)
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
