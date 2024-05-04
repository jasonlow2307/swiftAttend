from flask import Flask, request, jsonify, send_from_directory, Response, render_template
import boto3
import io
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr

app = Flask(__name__)

# Initialize Boto3 S3 client
s3 = boto3.client('s3')
initialized_date = ""
initialized_course = ""

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/register')
def register():
    return send_from_directory('.', 'registration.html')

@app.route('/init')
def init():
    return send_from_directory('.', 'initializeAttendance.html')

@app.route('/check')
def check():
    return send_from_directory('.', 'checkingAttendance.html')

@app.route('/ret')
def ret():
    return send_from_directory('.', 'retrieveAttendance.html')

@app.route('/initialize_class', methods=['POST'])
def initialize_class():
    global initialized_date
    global initialized_course

    date = request.form['date']
    course = request.form['course']
    start_time = request.form['time']
    class_datetime = datetime.strptime(date + ' ' + start_time, '%Y-%m-%d %H:%M')

    # Update global varaibles
    initialized_date = str(class_datetime)
    initialized_course = course

    # Fetch list of students from 'swiftAttend' table
    # Assume you have a function to fetch students from DynamoDB
    students = fetch_students_from_dynamodb()

    # Initialize class in 'swiftAttendance' table
    class_record = {
        'Course': course,
        'StartTime': class_datetime,
        'Students': students  # Assuming 'Students' is a list of student records fetched from 'swiftAttend' table
    }
    
    # Save class record to 'swiftAttendance' table
    # Assume you have a function to save class record to DynamoDB
    save_class_record_to_dynamodb(class_record)
    
    # Redirect the user to '/check' route after class initialization
    return jsonify({'success': True, 'message': 'Class initialized successfully!'}), 200


def fetch_students_from_dynamodb():
    dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
    response = dynamodb.scan(
        TableName='swiftAttend'
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

def save_class_record_to_dynamodb(class_record):
    dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
    table_name = 'swiftAttendance'  # Update with your table name

    course = class_record['Course']
    students = class_record['Students']
    
    for student in students:
        item = {
            'Date': {'S': str(class_record['StartTime'])},
            'Course': {'S': course},
            'FullName': {'S': student['FullName']},
            'StudentId': {'S': student['StudentId']},
            'Attendance': {'S': ""}
        }
        
        dynamodb.put_item(
            TableName=table_name,
            Item=item
        )


@app.route('/save', methods=['POST'])
def save():
    image = request.files['image']
    name = request.form['name']
    student_id = request.form['studentid']

    # Upload image to S3 bucket with metadata
    bucket_name = 'swift-attend-faces'
    key = f'index/{image.filename}'  # Object key in S3 bucket
    image_bytes = image.read()
    s3.upload_fileobj(
        io.BytesIO(image_bytes),
        bucket_name,
        key,
        ExtraArgs={'Metadata': {'FullName': name, 'student_id' : student_id}}
    )

    return '', 200  # Respond with success status code

@app.route('/detect', methods=['POST'])
def detect_faces():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    image_file = request.files['image']
    image_bytes = image_file.read()

    # Retrieve date and course from the form data
    date = request.form.get('date')
    course = request.form.get('course')

    # Initialize Boto3 Rekognition client
    rekognition = boto3.client('rekognition', region_name='ap-southeast-1')

    # Index all faces in the input image
    response_index = rekognition.index_faces(
        CollectionId='swiftAttend',
        Image={'Bytes': image_bytes}
    )

    # Extract face IDs from the response
    face_ids = [face['Face']['FaceId'] for face in response_index.get('FaceRecords', [])]
    
    detected_student_id = set()

    for face_id in face_ids:
        response_search = rekognition.search_faces(
            CollectionId = 'swiftAttend',
            FaceId = face_id, 
            FaceMatchThreshold=70,
            MaxFaces=10
        )

        if 'FaceMatches' in response_search and len(response_search['FaceMatches']) > 0:
                for match in response_search['FaceMatches']:
                    # Retrieve the information about the recognized person from DynamoDB
                    dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
                    person_info = dynamodb.get_item(
                        TableName='swiftAttend',
                        Key={'RekognitionId': {'S': match['Face']['FaceId']}}
                    )
                    if 'Item' in person_info:
                        #detected_people.add(person_info['Item']['FullName']['S'])
                        detected_student_id.add(person_info['Item']['StudentId']['S'])

    print(detected_student_id)


    # Fetch student records based on date and course
    student_records = fetch_student_in_class()

     # Initialize a list to store attendance records
    attendance_records = []

    # Iterate through student records and update attendance
    for student in student_records:
        attendance_status = 'PRESENT' if student['StudentId'] in detected_student_id else 'ABSENT'
        attendance_records.append({'FullName': student['FullName'], 'Attendance': attendance_status})
        # Update attendance in the database
        update_attendance(student['StudentId'], attendance_status, initialized_date)

    return render_template('attendance.html', attendance_records=attendance_records)

def fetch_student_in_class():
    dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
    response = dynamodb.scan(
        TableName='swiftAttendance',
        ExpressionAttributeNames={'#D': 'Date'},  # Alias for the reserved keyword 'Date'
        FilterExpression='#D = :d AND Course = :c',  # Using the alias and normal attribute name in the filter expression
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


def update_attendance(student_id, attendance, date):
    # Initialize Boto3 DynamoDB client
    dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
    
    # Update the item in DynamoDB table
    response = dynamodb.update_item(
        TableName='swiftAttendance',
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
    
    print(f"Attendance updated for student ID {student_id} on date {date} to {attendance}.")

@app.route('/retrieve', methods=['POST'])
def retrieve_attendance():
    # Get form data from the request
    course = request.form.get('course')
    date = request.form.get('date')
    student_id = request.form.get('studentId')

    print(course)
    print(date)
    print(student_id)

    # Define expression attribute values
    expression_attribute_values = {}

    # Define filter expression
    filter_expression = None

    if course:
        # Add course as a filter criterion
        filter_expression = Attr('Course').eq(course)

    if date:
        # Add date as a filter criterion
        if filter_expression:
            filter_expression = filter_expression & Attr('Date').eq(date)
        else:
            filter_expression = Attr('Date').eq(date)

    if student_id:
        # Add student ID as a filter criterion
        if filter_expression:
            filter_expression = filter_expression & Key('StudentId').eq(student_id)
        else:
            filter_expression = Key('StudentId').eq(student_id)

    # Fetch student records based on date and course using the fetch_student_in_class() method
    student_records = ret_student_in_class(course, date, student_id)

    # Render the attendance records template with the retrieved records
    return render_template('attendance_records.html', attendance_records=student_records)


def ret_student_in_class(course=None, date=None, time=None, student_id=None):
    dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
    
    # Initialize expression attribute names and values
    expression_attribute_names = {}
    expression_attribute_values = {}

    # Construct filter expression based on provided parameters
    filter_expression = None

    if course:
        expression_attribute_names['#C'] = 'Course'
        expression_attribute_values[':c'] = {'S': course}
        filter_expression = '#C = :c'

    if date:
        expression_attribute_names['#D'] = 'Date'
        expression_attribute_values[':d'] = {'S': date}
        if filter_expression:
            filter_expression += ' AND begins_with(#D, :d)'
        else:
            filter_expression = 'begins_with(#D, :d)'

    if time:
        if filter_expression:
            filter_expression += ' AND begins_with(#T, :t)'
        else:
            filter_expression = 'begins_with(#T, :t)'
        expression_attribute_names['#T'] = 'Date'
        expression_attribute_values[':t'] = {'S': time}

    if student_id:
        expression_attribute_names['#S'] = 'StudentId'
        expression_attribute_values[':s'] = {'S': student_id}
        if filter_expression:
            filter_expression += ' AND #S = :s'
        else:
            filter_expression = '#S = :s'

    # Query DynamoDB table based on the constructed filter expression
    response = dynamodb.scan(
        TableName='swiftAttendance',
        FilterExpression=filter_expression,
        ExpressionAttributeNames=expression_attribute_names,
        ExpressionAttributeValues=expression_attribute_values
    )

    # Extract attendance records from the response
    items = response.get('Items', [])
    students = []
    for item in items:
        student = {
            'FullName': item.get('FullName', {}).get('S'),
            'StudentId': item.get('StudentId', {}).get('S'),
            'Date': item.get('Date', {}).get('S'),
            'Attendance': item.get('Attendance', {}).get('S'),
            'Course': item.get('Course', {}).get('S')  # Include Course attribute
        }
        students.append(student)

    return students






if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


