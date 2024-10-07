from functools import wraps
from flask import Blueprint, redirect, render_template_string, send_from_directory, request, jsonify, render_template, url_for, session, Response
from datetime import datetime, timedelta, timezone
import io
from config import *
from common import *
import ast
import random
from datetime import datetime
import base64
from PIL import Image, ImageDraw
import time
import cv2
import face_recognition
from wrapper import *
from functions import *

attendance = Blueprint('attendance', __name__)

# Global variables
initialized_date = ''
initialized_course = ''
initialized = False

@attendance.route('/init')
@role_required(['lecturer', 'admin'])
def initialize():
    courses = fetch_courses_from_dynamodb(lecturer_id=session.get('id'))
    return render_template('initializeAttendance.html', courses=courses)

@attendance.route('/check')
@role_required(['lecturer', 'admin'])
def check_attendance():
    global initialized

    if not initialized:
        return render_template_string('''
                <script>
                    alert("You need to initialize the class first.");
                    window.location.href = "{{ url_for('attendance.initialize') }}";
                </script>
            ''')

    return send_from_directory('.', 'pages/checkingAttendance.html')

@attendance.route('/ret')
@login_required
def retrieve():
    courses = fetch_courses_from_dynamodb()
    return render_template('retrieveAttendance.html', courses=courses)

@attendance.route('/create')
@role_required(['lecturer', 'admin'])
def create_class():
    students = fetch_users_from_dynamodb("students")
    lecturers = fetch_users_from_dynamodb("lecturers")
    for student in students:
        student['StudentId'] = int(student['StudentId'])
    for lecturer in lecturers:
        lecturer['LecturerId'] = int(lecturer['LecturerId'])

    first_five_students = students[:5]
    remaining_students = students[5:]

    return render_template('createClass.html', first_five_students=first_five_students, remaining_students=remaining_students, lecturers = lecturers)

@attendance.route('/create_form', methods=['POST'])
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

@attendance.route('/init_form', methods=['POST'])
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

    # Calculate the TTL timestamp (30 minutes from now)
    ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(minutes=1)).timestamp())

    class_record = {
        'Course': selected_course['CourseCode'],
        'StartTime': date_and_time,
        'Students': matched_students,
        'ExpirationTime': ttl_timestamp  # Add TTL attribute
    }
    
    save_class_record(class_record)

    return jsonify({'success': True, 'message': 'Class initialized successfully!'}), 200


# LIVE ATTENDANCE MODE
# To store face detection timestamps and student IDs
face_timestamps = {}
face_to_student_map = {}
detected_students = {}
matched_faces = []
status = ""

known_face_encodings = []  # List to store face encodings of known faces
known_face_ids = []  # List to store face encodings of known faces

FACE_PROCESSING_COOLDOWN = 5  # Skip processing for 5 frames
face_processing_cooldown = {}

# Parameters
RESIZE_SCALE = 0.5  # Scale to reduce the resolution

def resize_frame(frame, scale=RESIZE_SCALE):
    width = int(frame.shape[1] * scale)
    height = int(frame.shape[0] * scale)
    dimensions = (width, height)
    resized_frame = cv2.resize(frame, dimensions, interpolation=cv2.INTER_AREA)
    return resized_frame

def process_frame(frame):
    global detected_students
    global status
    global known_face_encodings
    global known_face_ids
    global face_processing_cooldown

    # Resize frame for faster processing
    frame = resize_frame(frame)

    try:
        # Detect face locations
        face_locations = face_recognition.face_locations(frame)
    except Exception as e:
        print(f"Error in face_recognition.face_locations: {e}")
    # Encode faces in the frame
    face_encodings = face_recognition.face_encodings(frame, face_locations)

    current_time = time.time()

    for (face_encoding, (top, right, bottom, left)) in zip(face_encodings, face_locations):
        face_id = f"{top}_{right}_{bottom}_{left}"

        # Skip known faces
        if face_id in known_face_ids:
            continue

        if face_id in face_processing_cooldown and (current_time - face_processing_cooldown[face_id]) < FACE_PROCESSING_COOLDOWN:
            continue
        else:
            face_processing_cooldown[face_id] = current_time

        cv2.rectangle(frame, (left, top), (right, bottom), (255, 0, 0), 2)

        if status == "":
            status = "Face detected"
            print(status)

        # If the face is already stored in timestamps
        if face_id in face_timestamps:
            print("Time: " + str(current_time - face_timestamps[face_id]))
            if current_time - face_timestamps[face_id] > 3:
                if face_id not in face_to_student_map:
                    # Check face encoding against known faces
                    matches = face_recognition.compare_faces(known_face_encodings, face_encoding)

                    if True in matches:
                        # Face recognized
                        first_match_index = matches.index(True)
                        known_face_id = known_face_ids[first_match_index]
                        status = "Student has already been matched"
                        print(status)
                        cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)

                        if known_face_id not in matched_faces:
                            # Process recognized face (DynamoDB lookup, etc.)
                            process_recognized_face(known_face_id, face_id, frame, top, right, bottom, left)
                    else:
                        # Handle new faces with Rekognition
                        process_new_face_with_rekognition(face_encoding, face_id, frame, top, right, bottom, left)
        else:
            face_timestamps[face_id] = current_time

    return frame

def process_recognized_face(known_face_id, face_id, frame, top, right, bottom, left):
    global detected_students
    global matched_faces
    global status

    # Retrieve student details from DynamoDB
    person_info = dynamodb.get_item(
        TableName=DYNAMODB_STUDENT_TABLE_NAME,
        Key={'RekognitionId': {'S': known_face_id}}
    )

    if 'Item' in person_info:
        student_id = person_info['Item']['StudentId']['S']
        student_name = person_info['Item']['FullName']['S']
        student_image = generate_signed_url(S3_BUCKET_NAME, 'index/' + student_id)
        
        # Store detected student details
        detected_students[student_id] = {
            'name': student_name,
            'image': student_image
        }
        face_to_student_map[face_id] = student_id

        print(f"Detected student_id: {student_id} Name: {student_name}")
        print(student_image)

        # Update status and draw a green rectangle around recognized face
        matched_faces.append(known_face_id)
        status = "Student matched"
        print(status)
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)

def process_new_face_with_rekognition(face_encoding, face_id, frame, top, right, bottom, left):
    global known_face_encodings
    global known_face_ids
    global detected_students
    global status
    global matched_faces

    try:
        print("REKOGNITION")
        # Convert the detected face region to the required format for Rekognition
        face_region = frame[top:bottom, left:right]
        _, face_buffer = cv2.imencode('.jpg', face_region)
        face_bytes = face_buffer.tobytes()

        # Call Rekognition to search for the face
        response_search = rekognition.search_faces_by_image(
            CollectionId=REKOGNITION_COLLECTION_NAME,
            Image={'Bytes': face_bytes},
            FaceMatchThreshold=70,
            MaxFaces=10
        )

        # Process the search response
        face_matches = response_search.get('FaceMatches', [])
        if face_matches:
            for match in face_matches:
                face_id_from_rekognition = match['Face']['FaceId']
                person_info = dynamodb.get_item(
                    TableName=DYNAMODB_STUDENT_TABLE_NAME,
                    Key={'RekognitionId': {'S': face_id_from_rekognition}}
                )

                if 'Item' in person_info:
                    if person_info['Item']['RekognitionId']['S'] not in matched_faces:
                        student_id = person_info['Item']['StudentId']['S']
                        student_name = person_info['Item']['FullName']['S']
                        student_image = generate_signed_url(S3_BUCKET_NAME, 'index/' + student_id)
                        
                        # Store detected student details
                        detected_students[student_id] = {
                            'name': student_name,
                            'image': student_image
                        }
                        face_to_student_map[face_id] = student_id

                        print(f"Detected student_id: {student_id} Name: {student_name}")
                        print(student_image)

                        matched_faces.append(person_info['Item']['RekognitionId']['S'])
                        status = "Student matched"
                        print(status)

                        # Draw a green rectangle around the recognized face
                        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
                        
                        # Save the new face encoding and ID
                        known_face_encodings.append(face_encoding)
                        known_face_ids.append(face_id_from_rekognition)

    except rekognition.exceptions.InvalidParameterException as e:
        print("InvalidParameterException:", e)
        status = "Invalid face image"
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)

    except Exception as e:
        print("Error calling Rekognition:", e)
        status = "Error with Rekognition"
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)




@attendance.route('/detected_students')
def get_detected_students():
    return jsonify({
        'detected_students': detected_students,
        'status': status
    })

@attendance.route('/live')
def live():
    global initialized
    if not initialized:
        return render_template_string('''
                <script>
                    alert("You need to initialize the class first.");
                    window.location.href = "{{ url_for('attendance.initialize') }}";
                </script>
        ''')
    return render_template('live.html')
    
@attendance.route('/end_session', methods=['POST'])
def end_session():
    data = request.get_json()
    students = data.get('students', [])
    for student_id in students:
        update_attendance(student_id, 'PRESENT', initialized_date)
        print(f"Attendance updated for {student_id}")
    return jsonify({'success': True, 'message': 'Attendance updated successfully!'}), 200

@attendance.route('/show_attendance', methods=['GET'])
def show_attendance():
    attendance_records = []
    detected_student_id = detected_students.keys()

    student_records = fetch_student_records(initialized_date, initialized_course)

    attendance_records = []
    present_counter = 0

    for student in student_records:
        student_id = student['StudentId']
        attendance_status = 'PRESENT' if student_id in detected_student_id else 'ABSENT'
        if attendance_status == 'PRESENT':
            present_counter += 1
        image_key = 'index/' + student_id
        signed_url = generate_signed_url(S3_BUCKET_NAME, image_key)

        # Find emotion and eye direction for the student
        emotion = 'UNKNOWN'
        eye_direction = {'Yaw': 'UNKNOWN', 'Pitch': 'UNKNOWN'}

        attendance_records.append({
            'FullName': student['FullName'],
            'Attendance': attendance_status,
            'SignedURL': signed_url,
        })
    return render_template('checked_attendance.html', attendance_records=attendance_records)

# UPLOAD AND CAPTURE MODE
@attendance.route('/check_form', methods=['POST'])
def check_attendance_record():
    # Start timer
    start_time = time.time()

    global initialized_course
    global initialized_date
    global initialized

    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    image_file = request.files['image']
    image_bytes = image_file.read()

    # Check image size
    MAX_IMAGE_SIZE = 5242880  # 5 MB in bytes
    if len(image_bytes) > MAX_IMAGE_SIZE:
        # Resize the image if it exceeds the size limit
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        # Example calculation to preserve aspect ratio
        original_width, original_height = image.size
        max_dimension = 1024  # Example maximum dimension

        if original_width > original_height:
            # Landscape orientation
            new_width = max_dimension
            new_height = int(original_height * (max_dimension / original_width))
        else:
            # Portrait or square orientation
            new_height = max_dimension
            new_width = int(original_width * (max_dimension / original_height))
        resized_image = image.resize((new_width, new_height))  # Adjust new_width and new_height
        buffered = io.BytesIO()
        resized_image.save(buffered, format="JPEG")  # Change format as needed
        image_bytes = buffered.getvalue()
    else:
        # Use original image bytes
        image_bytes = image_bytes

    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    image_data_url = f"data:image/jpeg;base64,{image_base64}"

    # Open image using Pillow
    image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    draw = ImageDraw.Draw(image)

    # Detect faces and attributes in the image
    response_faces = rekognition.detect_faces(
        Image={'Bytes': image_bytes},
        Attributes=['ALL']
    )

    face_details = response_faces.get('FaceDetails', [])
    face_emotions = {}
    face_eye_directions = {}
    bounding_boxes = {}

    # Index faces in the collection
    response_index = rekognition.index_faces(
        CollectionId=REKOGNITION_COLLECTION_NAME,
        Image={'Bytes': image_bytes}
    )

    face_ids = [face['Face']['FaceId'] for face in response_index.get('FaceRecords', [])]
    detected_student_id = set()
    face_to_student_map = {}

    for face_record in response_index.get('FaceRecords', []):
        face_id = face_record['Face']['FaceId']
        bounding_box = face_record['FaceDetail']['BoundingBox']
        bounding_boxes[face_id] = bounding_box

    print("Bounding boxes: ", len(bounding_boxes))

    for face_detail in face_details:
        bounding_box = face_detail['BoundingBox']
        emotions = face_detail.get('Emotions', [])
        dominant_emotion = max(emotions, key=lambda x: x['Confidence'])['Type'] if emotions else 'UNKNOWN'
        pose = face_detail.get('Pose', {})
        yaw = pose.get('Yaw', 'UNKNOWN')
        pitch = pose.get('Pitch', 'UNKNOWN')

        # Find the face ID for this face by matching the bounding boxes
        face_id = next((fid for fid, box in bounding_boxes.items() if box == bounding_box), None)
        if face_id:
            face_emotions[face_id] = dominant_emotion
            face_eye_directions[face_id] = {'Yaw': yaw, 'Pitch': pitch}

            # Search for matches in the collection
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
                        student_id = person_info['Item']['StudentId']['S']
                        detected_student_id.add(student_id)
                        face_to_student_map[face_id] = student_id

    student_records = fetch_student_records(initialized_date, initialized_course)

    attendance_records = []
    present_counter = 0

    for student in student_records:
        student_id = student['StudentId']
        attendance_status = 'PRESENT' if student_id in detected_student_id else 'ABSENT'
        if attendance_status == 'PRESENT':
            present_counter += 1
        image_key = 'index/' + student_id
        signed_url = generate_signed_url(S3_BUCKET_NAME, image_key)

        # Find emotion and eye direction for the student
        emotion = 'UNKNOWN'
        eye_direction = {'Yaw': 'UNKNOWN', 'Pitch': 'UNKNOWN'}
        for face_id, mapped_student_id in face_to_student_map.items():
            if mapped_student_id == student_id:
                emotion = face_emotions.get(face_id, 'UNKNOWN')
                eye_direction = face_eye_directions.get(face_id, {'Yaw': 'UNKNOWN', 'Pitch': 'UNKNOWN'})
                break

        focused = is_focused(emotion, eye_direction)

        attendance_records.append({
            'FullName': student['FullName'],
            'Attendance': attendance_status,
            'SignedURL': signed_url,
            'Emotion': emotion,
            'EyeDirection': eye_direction,
            'Focused': focused
        })
        update_attendance(student_id, attendance_status, initialized_date)

    # Draw bounding boxes around detected faces
    for face_id, bounding_box in bounding_boxes.items():
        color = generate_random_color()
        width, height = image.size
        left = int(bounding_box['Left'] * width)
        top = int(bounding_box['Top'] * height)
        right = int(left + bounding_box['Width'] * width)
        bottom = int(top + bounding_box['Height'] * height)
        draw.rectangle([left, top, right, bottom], outline=color, width=3)

    if present_counter == 0:
        error = "The people in the image are not in the course, please check if the image is correct"
    else:
        error = ""

    # Convert modified image to base64
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    modified_image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    modified_image_data_url = f"data:image/jpeg;base64,{modified_image_base64}"

    # Reset initialized global variable
    initialized = False

    # End the timer and print the elapsed time
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Time taken to run check_attendance_record function: {elapsed_time} seconds")

    return render_template('checked_attendance.html', attendance_records=attendance_records, error=error, uploaded_image=modified_image_data_url)


@attendance.route('/ret_form', methods=['POST'])
def retrieve_attendance_records():
    start_time = time.time()

    role = session.get('role')
    id = session.get('id')
    course = request.form.get('course')
    # Convert the course string to a dictionary only if not default course
    if course != "DEFAULT":
        course = ast.literal_eval(course)
        # Extract the course code from the course string
        course = course ['CourseCode']
    date = request.form.get('date')
    time_form = request.form.get('time')

    if date and not time_form:
        return render_template('error.html', message='Time is required when date is provided.')
    
    student_records = retrieve_student_records(course, date, time_form)

    if not student_records:
        return render_template('error.html', message='No records found.')
    
    if role == 'student':
        student_records = [record for record in student_records if record['StudentId'] == int(id)]

    # End the timer and print the elapsed time
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Time taken to run retrieve_attendance_records function: {elapsed_time} seconds")
    
    return render_template('attendance_records.html', attendance_records=student_records)

######################### HELPER FUNCTION #########################
def generate_random_color():
    return tuple(random.randint(0, 255) for _ in range(3))

def is_focused(emotion, eye_direction):
    if emotion == 'UNKNOWN' or eye_direction['Yaw'] == 'UNKNOWN' or eye_direction['Pitch'] == 'UNKNOWN':
        return False
    
    print("EMOTION: ", emotion)
    print("EYE DIRECTION: ", eye_direction)
    focused_emotions = ["CALM", "HAPPY"]
    yaw_threshold = 16  # Yaw angle within -15 to +15 degrees
    pitch_threshold = 25  # Pitch angle within -15 to +15 degrees
    
    is_emotion_focused = emotion in focused_emotions
    is_looking_straight = abs(eye_direction['Yaw']) <= yaw_threshold and abs(eye_direction['Pitch']) <= pitch_threshold
    
    return is_emotion_focused and is_looking_straight