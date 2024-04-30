from flask import Flask, request, jsonify, send_from_directory, redirect, url_for
import boto3
import io
from datetime import datetime
from boto3.dynamodb.conditions import Key

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
        attendance_records.append({'FullName': student['FullName'], 'StudentId': student['StudentId'], 'Attendance': attendance_status})
        # Update attendance in the database
        update_attendance(student['StudentId'], attendance_status, initialized_date)

    return jsonify({'attendance_records': attendance_records}), 200


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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


