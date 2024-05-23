from functools import wraps
import re
from flask import Blueprint, redirect, render_template_string, send_from_directory, request, jsonify, render_template, url_for, session
from datetime import datetime
import io
from config import *
from botocore.exceptions import ClientError
from common import *
import ast
import random
from datetime import datetime
from flask_wtf import FlaskForm
from wtforms import FileField, StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email

blueprint = Blueprint('app', __name__)

initialized_date = ''
initialized_course = ''
initialized = False
class RegisterForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    given_name = StringField('Given Name', validators=[DataRequired()])
    family_name = StringField('Family Name', validators=[DataRequired()])
    role = SelectField('Role', choices=[('student', 'Student'), ('lecturer', 'Lecturer'), ('admin', 'Admin')], validators=[DataRequired()])
    image = FileField('Image', default='default.jpg')
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
        name = given_name + " " + family_name
        image = form.image.data
        role = form.role.data
        id = generate_id(role)
        try:
            response = cognito.sign_up(
                ClientId=COGNITO_CLIENT_ID,
                Username=email,
                Password=password,
                UserAttributes=[
                    {'Name': 'given_name', 'Value': given_name},
                    {'Name': 'family_name', 'Value': family_name},
                    {'Name': 'custom:role', 'Value': role},
                    {'Name': 'custom:id', 'Value': id}
                ]
            )
            # Save the user's email in the session
            session['email'] = email

            # Use the generated ID in your code
            bucket_name = S3_BUCKET_NAME
            key = f'index/{id}'
            image_bytes = image.read()
            s3.upload_fileobj(
                io.BytesIO(image_bytes),
                bucket_name,
                key,
                ExtraArgs={'Metadata': {'FullName': name, 'id': id, 'role': role}}
            )

            return redirect(url_for('app.confirm'))
        except ClientError as e:
            # Print the entire exception object
            print(f"Exception: {e}")
            
            # Print the full error response
            if 'Error' in e.response:
                print(f"Error Code: {e.response['Error']['Code']}")
                print(f"Error Message: {e.response['Error']['Message']}")
                print(f"Error Response: {e.response}")
            
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
                id_token = response['AuthenticationResult']['IdToken']
                session['id_token'] = id_token

                # Decode the ID token to get user attributes
                user_info = cognito.get_user(AccessToken=response['AuthenticationResult']['AccessToken'])
                role = next(attr['Value'] for attr in user_info['UserAttributes'] if attr['Name'] == 'custom:role')
                id = next(attr['Value'] for attr in user_info['UserAttributes'] if attr['Name'] == 'custom:id')
                session['role'] = role
                session['id'] = id
                print("ID")
                print(id)
                return redirect(url_for('app.index'))
            else:
                error = response.get('ChallengeName', 'Authentication failed. Please check your email and password.')
                return render_template('login.html', form=form, error=error)
        except ClientError as e:
            error = e.response['Error']['Message']
            return render_template('login.html', form=form, error=error)
    return render_template('login.html', form=form)

def role_required(roles):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'id_token' not in session or 'role' not in session:
                return render_template_string('''
                    <script>
                        alert("You need to log in first.");
                        window.location.href = "{{ url_for('app.login') }}";
                    </script>
                ''')
            if session['role'] not in roles:
                return render_template_string('''
                    <script>
                        alert("You do not have permission to access this page.");
                        window.location.href = "{{ url_for('app.index') }}";
                    </script>
                ''')
            return f(*args, **kwargs)
        return decorated_function
    return wrapper


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
                attendance_rate = round(present_counter / total_records * 100, 2)
                course['AttendanceRate'] = attendance_rate
            else:
                course['AttendanceRate'] = "NA"
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
        students = fetch_users_from_dynamodb("students")
    else:
        user = {'FullName': {'S': "Admin"}}

    welcome_message = f"Welcome back, {user['FullName']['S']} ({id})"

    if role == 'student':
        return render_template('index_student.html', user=user, courses=courses)
    elif role == 'lecturer':
        return render_template('index_lecturer.html', user=user, courses=courses, students=students)
    else:
        return render_template('index_admin.html', welcome_message=welcome_message)

@blueprint.route('/bot')
def bot():
    return render_template('bot.html')

@blueprint.route('/bot_form', methods=['POST'])
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
    if messages:
        bot_message = messages[0]['content']
    else:
        bot_message = "Sorry, I didn't understand that."

    return jsonify({'message': bot_message})

@blueprint.route('/courses')
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
@blueprint.route('/add_student', methods=['POST'])
def add_student():
    data = request.get_json()
    student_id = data['studentId']
    course_code = data['courseCode']

    print(student_id)

    edit_student_in_course(student_id, course_code, True)
    return jsonify({'success': True, 'message': 'Student added successfully!'}), 200

# For removing students from course
@blueprint.route('/remove_student', methods=['POST'])
def remove_student():
    data = request.get_json()
    student_id = data['studentId']
    course_code = data['courseCode']

    print(student_id)

    edit_student_in_course(student_id, course_code, False)

    return jsonify({'success': True, 'message': 'Student removed successfully!'}), 200

@blueprint.route('/reglec')
@role_required(['lecturer','admin'])
def registerLec():
    return send_from_directory('.', 'pages/registerLecturer.html')

@blueprint.route('/regstd')
@login_required
def registerStd():
    return send_from_directory('.', 'pages/registerStudent.html')

@blueprint.route('/init')
@role_required(['lecturer', 'admin'])
def initialize():
    courses = fetch_courses_from_dynamodb()
    return render_template('initializeAttendance.html', courses=courses)

@blueprint.route('/check')
@role_required(['lecturer', 'admin'])
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
@role_required(['lecturer', 'admin'])
def create_class():
    students = fetch_users_from_dynamodb("students")
    lecturers = fetch_users_from_dynamodb("lecturers")
    for student in students:
        student['StudentId'] = int(student['StudentId'])
    for lecturer in lecturers:
        lecturer['LecturerId'] = int(lecturer['LecturerId'])
    return render_template('createClass.html', students=students, lecturers = lecturers)

@blueprint.route('/create_form', methods=['POST'])
def create_class_record():
    course_name = request.form['courseName']
    course_code = request.form['courseCode']
    day = request.form['day']
    time = request.form['time']
    # Getting list of students and lecturers in string 
    selected_students = request.form.getlist('students')
    selected_lecturer = request.form['lecturer']
    # List to store converted students and lecrturer in proper dictionary format
    selected_students_dic = []
    for student in selected_students:
        student = ast.literal_eval(student)
        student['StudentId'] = str(student['StudentId'])
        selected_students_dic.append(student)

    # Convert selected lecturer to dictionary
    selected_lecturer = ast.literal_eval(selected_lecturer)
    selected_lecturer['LecturerId'] = str(selected_lecturer['LecturerId'])
    
    # Join all student ids of selected students with | separator
    selected_student_ids = "|".join(student['StudentId'] for student in selected_students_dic)

    item = {
        'CourseCode': {'S': course_code},
        'CourseName': {'S': course_name},
        'Day': {'S': day},
        'Time': {'S': time},
        'Students': {'S': selected_student_ids},
        'Lecturer': {'S': selected_lecturer['LecturerId']}
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

    matched_students = fetch_users_from_dynamodb("students", student_ids)

    class_record = {
        'Course': selected_course['CourseCode'],
        'StartTime': date_and_time,
        'Students': matched_students
    }
    
    save_class_record(class_record)

    return jsonify({'success': True, 'message': 'Class initialized successfully!'}), 200

@blueprint.route('/regstdlec_form', methods=['POST'])
def save_lecturer_registration():
    image = request.files['image']
    name = request.form['name']
    role = request.form['role']

    id = generate_id(role)

    # Use the generated ID in your code
    bucket_name = S3_BUCKET_NAME
    key = f'index/{id}'
    image_bytes = image.read()
    s3.upload_fileobj(
        io.BytesIO(image_bytes),
        bucket_name,
        key,
        ExtraArgs={'Metadata': {'FullName': name, 'id': id, 'role': role}}
    )

    return '', 200

def generate_id(role):
    # Generate ID
    year_month = datetime.now().strftime('%y%m')
    if role == 'student':
        # student's fifth digit is 1 to 5
        random_numbers = str(random.randint(1000, 5999))
        id = year_month + random_numbers
        # Check if id already exists in table
        response = dynamodb.scan(
            TableName=DYNAMODB_STUDENT_TABLE_NAME,
            FilterExpression='studentId = :student_id',
            ExpressionAttributeValues={':student_id': {'S': id}}
        )
        items = response.get('Items', [])
        while items:
            # Regenerate student_id
            random_numbers = str(random.randint(1000, 5999))
            id = year_month + random_numbers
            response = dynamodb.scan(
                TableName=DYNAMODB_STUDENT_TABLE_NAME,
                FilterExpression='studentId = :student_id',
                ExpressionAttributeValues={':student_id': {'S': id}}
            )
            items = response.get('Items', [])
    else:
        # lecturer's fifth digit is 6 to 9
        random_numbers = str(random.randint(6000, 9999))
        id = year_month + random_numbers
        response = dynamodb.scan(
            TableName=DYNAMODB_LECTURER_TABLE_NAME,
            FilterExpression='lecturerId = :lecturer_id',
            ExpressionAttributeValues={':lecturer_id': {'S': id}}
        )
        items = response.get('Items', [])
        while items:
            # Regenerate lecturer_id
            random_numbers = str(random.randint(6000, 9999))
            id = year_month + random_numbers
            response = dynamodb.scan(
                TableName=DYNAMODB_LECTURER_TABLE_NAME,
                FilterExpression='lecturerId = :lecturer_id',
                ExpressionAttributeValues={':lecturer_id': {'S': id}}
            )
            items = response.get('Items', [])
    id = year_month + random_numbers
    return id

    

    

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
                        TableName=DYNAMODB_STUDENT_TABLE_NAME,
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
    role = session.get('role')
    id = session.get('id')
    course = request.form.get('course')
    # Convert the course string to a dictionary only if not default course
    if course != "DEFAULT":
        course = ast.literal_eval(course)
        # Extract the course code from the course string
        course = course ['CourseCode']
    date = request.form.get('date')
    time = request.form.get('time')

    if date and not time:
        return render_template('error.html', message='Time is required when date is provided.')
    
    student_records = retrieve_student_records(course, date, time)

    if not student_records:
        return render_template('error.html', message='No records found.')
    
    if role == 'student':
        student_records = [record for record in student_records if record['StudentId'] == int(id)]
    
    return render_template('attendance_records.html', attendance_records=student_records)

############################ Custom Functions ###########################
# Adding/removing student id from a course student field
def edit_student_in_course(student_id, course_code, add=True):
    matched_course = fetch_courses_from_dynamodb(course_code=course_code)
    if not add:
        matched_course['Students'] = re.sub(r'\|' + re.escape(student_id), '', matched_course['Students'])
        print(str(student_id) + " removed")
    else:
        matched_course['Students'] += '|' + student_id
        print(str(student_id) + " added")
    update_classes_table(course_code, matched_course['CourseName'], matched_course['Students'])
    print(matched_course['Students'])

# Update record in classes table
def update_classes_table(course_code, course_name, students):
    dynamodb.update_item(
        TableName=DYNAMODB_CLASSES_TABLE_NAME,
        Key={'CourseCode': {'S': course_code}, 'CourseName': {'S': course_name}},
        UpdateExpression='SET Students = :students',
        ExpressionAttributeValues={':students': {'S': students}},
        ReturnValues='UPDATED_NEW'  # You can specify the desired return values as needed
    )

    return {'success': True, 'message': f'Students updated for course {course_code} successfully!'}, 200

# For /init
# Fetch all classes from the classes table
def fetch_courses_from_dynamodb(course_code=None, lecturer_id=None, student_id=None):
    response = dynamodb.scan(TableName=DYNAMODB_CLASSES_TABLE_NAME)
    items = response.get('Items', [])
    courses = []

    for item in items:
        course = {
            'CourseCode': item.get('CourseCode', {}).get('S'),
            'CourseName': item.get('CourseName', {}).get('S'),
            'Day': item.get('Day', {}).get('S'),
            'Time': item.get('Time', {}).get('S'),
            'Students': item.get('Students', {}).get('S'),
            'Lecturer': item.get('Lecturer', {}).get('S')
        }

        if course_code is not None and course['CourseCode'] == course_code:
            return course  # If specified course_code, only return one course

        if lecturer_id is not None and course['Lecturer'] == lecturer_id:
            courses.append(course)
            continue  # Continue to the next iteration instead of returning immediately

        if student_id is not None and course['Students'].find(student_id) != -1:
            courses.append(course)
            continue  # Continue to the next iteration instead of returning immediately

        if course_code is None and lecturer_id is None and student_id is None:
            courses.append(course)

    return courses

# For /create and /create_form
# Return all students from registration table
def fetch_users_from_dynamodb(target, user_ids=None):
    if target == "students":
        table_name = DYNAMODB_STUDENT_TABLE_NAME
        id_key = 'StudentId'
        name_key = 'FullName'
    elif target == "lecturers":
        table_name = DYNAMODB_LECTURER_TABLE_NAME
        id_key = 'LecturerId'
        name_key = 'FullName'
    else:
        return []

    response = dynamodb.scan(
        TableName=table_name
    )
    items = response.get('Items', [])
    users = []

    if user_ids is None:
        for item in items:
            user = {
                name_key: item.get(name_key, {}).get('S'),
                id_key: item.get(id_key, {}).get('S')
            }
            users.append(user)
    else:
        for user_id in user_ids:
            response = dynamodb.scan(
                TableName=table_name,
                FilterExpression=f'{id_key} = :user_id',
                ExpressionAttributeValues={':user_id': {'S': user_id}}
            )
            items = response.get('Items', [])
            users.extend(items)

    return users

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

# For /ret_form
# Retrieve attendance records based on provided parameters
def retrieve_student_records(course=None, date=None, time=None):
    expression_attribute_names = {}
    expression_attribute_values = {}

    filter_expression_parts = []

    if course != "DEFAULT" or date:
        if course != "DEFAULT":
            expression_attribute_names['#C'] = 'Course'
            expression_attribute_values[':c'] = {'S': course}
            filter_expression_parts.append('#C = :c')

        if date:
            date_and_time = datetime.strptime(date + ' ' + time, '%Y-%m-%d %H:%M')
            expression_attribute_names['#D'] = 'Date'
            date_str = str(date_and_time)
            expression_attribute_values[':d'] = {'S': date_str}
            filter_expression_parts.append('begins_with(#D, :d)')

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
    
    return None

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
