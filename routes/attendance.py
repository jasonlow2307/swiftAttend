import botocore
from flask import Blueprint, render_template_string, send_from_directory, request, jsonify, render_template, url_for, session, Response
from datetime import datetime, timedelta, timezone
import io
import numpy as np
from config import *
from common import *
import ast
import random
from datetime import datetime
import base64
from PIL import Image, ImageDraw
import time
import cv2
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
import mediapipe as mp
import uuid

# Initialize mediapipe Face Detection
# Initialize mediapipe Face Detection
mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(min_detection_confidence=0.5)

# Global variables for face tracking and status
frame_count = 0
process_every_nth_frame = 4  # Process every 4th frame to optimize performance
previous_faces = {}  # Dictionary to track previous face locations, IDs, and status
face_to_student_map = {}  # Maps AWS Rekognition face IDs to student names/details
recognized_faces = {} # To keep track of already recognized face IDs
status = ""  # Status variable to track the current processing stage
detected_students = {}

# Rekognition and tracking parameters
FACE_HOLD_TIME = 2  # Time (in seconds) a face must be held before triggering Rekognition
INITIAL_COOLDOWN = 3  # Initial cooldown time for unrecognized faces
MAX_REKOGNITION_ATTEMPTS = 5  # Number of Rekognition attempts before increasing cooldown
INCREASED_COOLDOWN = 10  # Cooldown after max attempts reached
FACE_REMOVAL_TIME = 5  # Time (in seconds) after which missing faces are removed

# Helper function to resize frames
def resize_frame(frame, scale=0.5):
    """Resize frame for optimized processing."""
    width = int(frame.shape[1] * scale)
    height = int(frame.shape[0] * scale)
    dimensions = (width, height)
    return cv2.resize(frame, dimensions, interpolation=cv2.INTER_AREA)

def calculate_distance(box1, box2):
    """Calculate Euclidean distance between the centers of two bounding boxes."""
    (x1, y1, w1, h1) = box1
    (x2, y2, w2, h2) = box2
    center1 = (x1 + w1 // 2, y1 + h1 // 2)
    center2 = (x2 + w2 // 2, y2 + h2 // 2)
    return np.sqrt((center1[0] - center2[0]) ** 2 + (center1[1] - center2[1]) ** 2)

def track_faces(current_faces, previous_faces, threshold=50):
    """Track faces between current and previous frames based on bounding box positions."""
    tracked_faces = {}
    unmatched_prev_ids = set(previous_faces.keys())

    for curr_id, curr_data in current_faces.items():
        best_match = None
        min_distance = float('inf')

        # Try to match current faces with previous faces by distance
        for prev_id, prev_data in previous_faces.items():
            distance = calculate_distance(curr_data['box'], prev_data['box'])

            if distance < min_distance and distance < threshold:
                best_match = prev_id
                min_distance = distance

        if best_match is not None:
            # If a match is found, retain the previous ID and attributes
            tracked_faces[best_match] = curr_data
            tracked_faces[best_match]['timestamp'] = previous_faces[best_match]['timestamp']
            tracked_faces[best_match]['recognized'] = previous_faces[best_match]['recognized']
            tracked_faces[best_match]['rekognition_attempts'] = previous_faces[best_match]['rekognition_attempts']
            tracked_faces[best_match]['in_cooldown'] = previous_faces[best_match]['in_cooldown']
            tracked_faces[best_match]['last_recognition_time'] = previous_faces[best_match].get('last_recognition_time', 0)
            unmatched_prev_ids.discard(best_match)
        else:
            # If no match, consider it as a new face
            new_id = str(uuid.uuid4())
            curr_data['timestamp'] = time.time()
            tracked_faces[new_id] = curr_data

    # Retain unmatched previous faces if they are still in the frame
    for prev_id in unmatched_prev_ids:
        tracked_faces[prev_id] = previous_faces[prev_id]

    return tracked_faces

def process_frame(frame):
    global frame_count, previous_faces, status, recognized_faces

    # Skip frames to reduce processing load
    frame_count += 1
    if frame_count % process_every_nth_frame != 0:
        return frame

    # Resize frame for faster processing
    frame = resize_frame(frame, scale=0.4)
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # Perform face detection
    results = face_detection.process(rgb_frame)

    # Prepare a dictionary to store the current frame's face bounding boxes
    current_faces = {}

    current_time = time.time()

    if results.detections:
        for detection in results.detections:
            bboxC = detection.location_data.relative_bounding_box
            ih, iw, _ = frame.shape
            x, y, w, h = int(bboxC.xmin * iw), int(bboxC.ymin * ih), int(bboxC.width * iw), int(bboxC.height * ih)
            temp_id = str(uuid.uuid4())
            current_faces[temp_id] = {
                'box': (x, y, w, h), 
                'timestamp': current_time, 
                'recognized': False, 
                'in_cooldown': False, 
                'rekognition_attempts': 0
            }

    # Match the current frame's faces with the previous frame's faces to assign consistent IDs
    tracked_faces = track_faces(current_faces, previous_faces)

    # Remove faces that haven't been detected for a while
    faces_to_remove = []
    for face_id, face_data in previous_faces.items():
        # If the face hasn't been seen for more than FACE_REMOVAL_TIME, mark it for removal
        if current_time - face_data['timestamp'] > FACE_REMOVAL_TIME:
            faces_to_remove.append(face_id)

    # Remove the faces from previous_faces
    for face_id in faces_to_remove:
        del tracked_faces[face_id]
        print(f"Removed face ID {face_id} due to inactivity.")

    # Update the previous_faces with the tracked_faces
    previous_faces = tracked_faces

    # Process each tracked face
    for face_id, face_data in tracked_faces.items():
        (x, y, w, h) = face_data['box']

        # Skip Rekognition if face has already been recognized
        if face_data['recognized'] or face_id in recognized_faces:
            # Draw bounding box for recognized face
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)  # Green for recognized
            cv2.putText(frame, f"Recognized: {face_to_student_map.get(face_id, 'Student')}", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            continue

        # If face has been in the frame for 3 seconds and is not in cooldown
        if not face_data['in_cooldown'] and (current_time - face_data['timestamp']) >= FACE_HOLD_TIME:
            print(f"Face ID {face_id[:8]} ready for Rekognition (attempt {face_data['rekognition_attempts'] + 1}).")

            # Set cooldown before calling Rekognition
            face_data['in_cooldown'] = True
            face_data['last_recognition_time'] = current_time

            # Call AWS Rekognition for recognition
            face_region = frame[y:y + h, x:x + w]
            matches = call_rekognition(face_region)
            if matches:
                rekognition_id = matches[0]['Face']['FaceId']
                face_data['recognized'] = True
                face_to_student_map[face_id] = f"Student_{rekognition_id[:8]}"
                
                # Update recognized_faces to prevent future Rekognition calls
                recognized_faces[face_id] = rekognition_id

                # Update detected students and prevent further calls for this face
                update_detected_students(rekognition_id)
                print(f"Face ID {rekognition_id} recognized. Will not reprocess.")
            else:
                # No match found, increase Rekognition attempts and keep the cooldown active
                face_data['rekognition_attempts'] += 1
                print(f"Face ID {face_id[:8]} not recognized. Setting cooldown.")

        # Check if cooldown period has expired
        if face_data['in_cooldown']:
            cooldown_time = INITIAL_COOLDOWN if face_data['rekognition_attempts'] <= MAX_REKOGNITION_ATTEMPTS else INCREASED_COOLDOWN
            time_since_last_recognition = current_time - face_data['last_recognition_time']
            
            print(f"Face ID {face_id[:8]} is in cooldown. Time since last recognition: {time_since_last_recognition:.2f} seconds.")

            if time_since_last_recognition >= cooldown_time:
                face_data['in_cooldown'] = False
                print(f"Cooldown expired for Face ID {face_id[:8]}. Ready for another attempt.")

        # Draw bounding boxes and labels
        color = (0, 255, 0) if face_data['recognized'] else (0, 0, 255)  # Green for recognized, red for unrecognized
        label = face_to_student_map.get(face_id, f"Unknown (Attempts: {face_data['rekognition_attempts']})")
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        cv2.putText(frame, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    return frame

def call_rekognition(face_image):
    """Send the cropped face to AWS Rekognition and return the result."""
    print("Calling AWS Rekognition...")
    _, face_bytes = cv2.imencode('.jpg', face_image)
    response = rekognition.search_faces_by_image(
        CollectionId=REKOGNITION_COLLECTION_NAME,
        Image={'Bytes': face_bytes.tobytes()},
        FaceMatchThreshold=70,
        MaxFaces=1
    )
    return response.get('FaceMatches', [])

def update_detected_students(rekognition_id):
    global detected_students

    student_info = dynamodb.get_item(
        TableName=DYNAMODB_STUDENT_TABLE_NAME,
        Key={'RekognitionId': {'S': rekognition_id}}
    )

    if 'Item' in student_info:
        student_id = student_info['Item']['StudentId']['S']
        student_name = student_info['Item']['FullName']['S']
        student_image = generate_signed_url(S3_BUCKET_NAME, 'index/' + student_id)
        
        # Store detected student details
        detected_students[student_id] = {
            'name': student_name,
            'image': student_image
        }

        print(f"Detected student_id: {student_id} Name: {student_name}")
        


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
            'Emotion': emotion,
            'EyeDirection': eye_direction,
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
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        original_width, original_height = image.size
        max_dimension = 1024

        if original_width > original_height:
            new_width = max_dimension
            new_height = int(original_height * (max_dimension / original_width))
        else:
            new_height = max_dimension
            new_width = int(original_width * (max_dimension / original_height))
        
        resized_image = image.resize((new_width, new_height))
        buffered = io.BytesIO()
        resized_image.save(buffered, format="JPEG")
        image_bytes = buffered.getvalue()

    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    image_data_url = f"data:image/jpeg;base64,{image_base64}"

    # Open image using Pillow
    image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    draw = ImageDraw.Draw(image)

    # Detect faces and attributes in the image using detect_faces
    response_faces = rekognition.detect_faces(
        Image={'Bytes': image_bytes},
        Attributes=['ALL']
    )

    face_details = response_faces.get('FaceDetails', [])
    face_emotions = {}
    face_eye_directions = {}
    bounding_boxes = {}
    detected_student_id = set()
    face_to_student_map = {}

    print(f"Detected {len(face_details)} face(s).")

    # Step 2: Draw bounding boxes around detected faces
    for face_detail in face_details:
        bounding_box = face_detail['BoundingBox']
        width, height = image.size
        left = int(bounding_box['Left'] * width)
        top = int(bounding_box['Top'] * height)
        right = int(left + bounding_box['Width'] * width)
        bottom = int(top + bounding_box['Height'] * height)
        color = generate_random_color()  # Custom function to generate random color
        draw.rectangle([left, top, right, bottom], outline=color, width=3)

        emotions = face_detail.get('Emotions', [])
        dominant_emotion = max(emotions, key=lambda x: x['Confidence'])['Type'] if emotions else 'UNKNOWN'
        pose = face_detail.get('Pose', {})
        yaw = pose.get('Yaw', 'UNKNOWN')
        pitch = pose.get('Pitch', 'UNKNOWN')

        face_emotions[bbox_to_key(bounding_box)] = dominant_emotion
        face_eye_directions[bbox_to_key(bounding_box)] = {'Yaw': yaw, 'Pitch': pitch}

        # Crop face from the image for indexing
        face_image = image.crop((left, top, right, bottom))

        # Convert cropped face to bytes
        buffered_face = io.BytesIO()
        face_image.save(buffered_face, format="JPEG")
        face_bytes = buffered_face.getvalue()

        # Step 3: Index the face to get FaceId
        response_index = rekognition.index_faces(
            CollectionId=REKOGNITION_COLLECTION_NAME,
            Image={'Bytes': face_bytes},
            MaxFaces=1,
            DetectionAttributes=['DEFAULT']
        )

        # Check if face is indexed and get FaceId
        if response_index.get('FaceRecords'):
            face_id = response_index['FaceRecords'][0]['Face']['FaceId']
            print(f"Indexed FaceId: {face_id}")

            # Step 4: Attempt Rekognition search 3 times
            face_found = False
            for attempt in range(3):
                try:
                    response_search = rekognition.search_faces(
                        CollectionId=REKOGNITION_COLLECTION_NAME,
                        FaceId=face_id,
                        FaceMatchThreshold=20,
                        MaxFaces=50
                    )

                    if 'FaceMatches' in response_search and len(response_search['FaceMatches']) > 0:
                        face_found = True
                        for match in response_search['FaceMatches']:
                            person_info = dynamodb.get_item(
                                TableName=DYNAMODB_STUDENT_TABLE_NAME,
                                Key={'RekognitionId': {'S': match['Face']['FaceId']}}
                            )
                            if 'Item' in person_info:
                                student_id = person_info['Item']['StudentId']['S']
                                detected_student_id.add(student_id)
                                face_to_student_map[bbox_to_key(bounding_box)] = student_id
                        break  # Break out of the loop if a match is found
                    else:
                        print(f"No matches found for FaceId {face_id} (Attempt {attempt + 1})")

                except botocore.exceptions.ClientError as error:
                    if error.response['Error']['Code'] == 'InvalidParameterException':
                        print(f"FaceId {face_id} was not found in the Rekognition collection.")
                    else:
                        print(f"An unexpected error occurred: {error}")

            if not face_found:
                print(f"No match found for FaceId {face_id} after 3 attempts.")
            
            # Delete the indexed face after getting the FaceId
            rekognition.delete_faces(
                CollectionId=REKOGNITION_COLLECTION_NAME,
                FaceIds=[face_id]
            )
        else:
            print("No FaceRecords found during indexing.")

    # Process attendance records
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
        for bbox_key, mapped_student_id in face_to_student_map.items():
            if mapped_student_id == student_id:
                emotion = face_emotions.get(bbox_key, 'UNKNOWN')
                eye_direction = face_eye_directions.get(bbox_key, {'Yaw': 'UNKNOWN', 'Pitch': 'UNKNOWN'})
                if eye_direction != {'Yaw': 'UNKNOWN', 'Pitch': 'UNKNOWN'}:
                    eye_direction = {
                        'Yaw': round(eye_direction['Yaw'], 2),
                        'Pitch': round(eye_direction['Pitch'], 2)
                    }
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

    # Convert the modified image back to base64
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

    return render_template('checked_attendance.html', attendance_records=attendance_records, error='', uploaded_image=modified_image_data_url)

# Helper function to create a unique key for bounding boxes (useful for mapping to face IDs)
def bbox_to_key(bounding_box):
    return f"{bounding_box['Left']}_{bounding_box['Top']}_{bounding_box['Width']}_{bounding_box['Height']}"


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