import botocore
from flask import Blueprint, render_template_string, send_from_directory, request, jsonify, render_template, url_for, session
from datetime import datetime, timedelta, timezone
import io
import numpy as np
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
import uuid

attendance = Blueprint('attendance', __name__)

# Global variables
initialized_date = ''
initialized_course = ''
initialized = False

load_dotenv()
REKOGNITION_COLLECTION_NAME = os.getenv('REKOGNITION_COLLECTION_NAME')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
ATTENDANCE_PROCESSING_LOGS_TABLE_NAME = os.getenv('ATTENDANCE_PROCESSING_LOGS_TABLE_NAME')
ATTENDANCE_LIVE_PROCESSING_LOGS_TABLE_NAME = os.getenv('ATTENDANCE_LIVE_PROCESSING_LOGS_TABLE_NAME')
ATTENDANCE_LIVE_STUDENT_DETECTION_LOGS_TABLE_NAME = os.getenv('ATTENDANCE_LIVE_STUDENT_DETECTION_LOGS_TABLE_NAME')

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
    role = session.get('role')
    if (role == "student"):
        courses = fetch_courses_from_dynamodb(student_id=session.get('id'))        
    else:
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
    print(remaining_students)

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
    global initialized_date, initialized_course, initialized
    global  recognized_faces, detected_students
    global frame_count, previous_faces

    # Clear all tracking and recognition data
    recognized_faces = {}   # Clear recognized faces
    detected_students = {}   # Clear detected students
    previous_faces = {}     # Clear face tracking
    frame_count = 0        # Reset frame counter

    # Get form data
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
    
    print("Initialized new session - cleared all face tracking and recognition data")
    return jsonify({'success': True, 'message': 'Class initialized successfully!'}), 200

# LIVE ATTENDANCE MODE
import mediapipe as mp
import uuid

# Initialize mediapipe Face Detection
# Initialize mediapipe Face Detection
mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(min_detection_confidence=0.5)

def draw_modern_rectangle(frame, x, y, w, h, color, label, thickness=2, alpha=0.2):
    """Draw a modern-looking rectangle with overlay and text"""
    # Create overlay for transparent fill
    overlay = frame.copy()
    
    # Draw filled rectangle with transparency
    cv2.rectangle(overlay, (x, y), (x+w, y+h), color, -1)
    
    # Draw border with rounded corners (simulate by drawing lines)
    corner_length = 20  # Length of corner lines
    
    # Top left corner
    cv2.line(frame, (x+corner_length, y), (x, y), color, thickness)
    cv2.line(frame, (x, y), (x, y+corner_length), color, thickness)
    
    # Top right corner
    cv2.line(frame, (x+w-corner_length, y), (x+w, y), color, thickness)
    cv2.line(frame, (x+w, y), (x+w, y+corner_length), color, thickness)
    
    # Bottom left corner
    cv2.line(frame, (x, y+h-corner_length), (x, y+h), color, thickness)
    cv2.line(frame, (x, y+h), (x+corner_length, y+h), color, thickness)
    
    # Bottom right corner
    cv2.line(frame, (x+w, y+h-corner_length), (x+w, y+h), color, thickness)
    cv2.line(frame, (x+w, y+h), (x+w-corner_length, y+h), color, thickness)
    
    # Blend the overlay with the original frame
    cv2.addWeighted(overlay, alpha, frame, 1-alpha, 0, frame)
    
    # Add text with background
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    font_thickness = 2
    text_size = cv2.getTextSize(label, font, font_scale, font_thickness)[0]
    text_w, text_h = text_size
    
    # Draw text background
    cv2.rectangle(frame, 
                 (x, y-text_h-10),
                 (x+text_w+10, y),
                 color, -1)
    
    # Draw text
    cv2.putText(frame, label,
                (x+5, y-7),
                font, font_scale, (255, 255, 255),
                font_thickness)

    return frame

face_tracking = {}
# Add these global variables at the top
FACE_DETECTION_CONFIG = {
    'hold_time': 2,        # Time in seconds before recognition
    'position_threshold': 50,  # Pixel distance threshold
    'recognition_cooldown': 2, # Cooldown between recognition attempts
    'debug_mode': True     # Enable/disable debug prints
}

# Add at the top with other global variables
last_rekognition_call = 0  # Track the last time Rekognition was called
REKOGNITION_COOLDOWN = 2  # Cooldown period in seconds
# Add to global variables
DAILY_API_CALL_LIMIT = 100
status = ""

FACE_STATUS = {
    'INITIALIZING': "System initializing...",
    'NO_FACES': "No faces detected",
    'HOLD_STILL': "Please hold still for recognition",
    'PROCESSING': "Processing face...",
    'RECOGNIZED': "Student recognized!",
    'NOT_RECOGNIZED': "Face not recognized",
    'API_LIMIT': "Daily API limit reached",
    'COOLDOWN': "System cooldown active",
    'ERROR': "Error processing face"
}

def process_frame(frame):
    """Process frame with simplified face detection and recognition flow"""
    global face_tracking, status
    current_time = time.time()
    
    try:
        if frame is None or frame.size == 0:
            status = FACE_STATUS['INITIALIZING']
            return frame

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_detection.process(rgb_frame)

        if not results.detections:
            face_tracking.clear()
            status = FACE_STATUS['NO_FACES']
            return frame

        # Create a set of current faces for tracking
        current_faces = set()

        # 2. Process each detected face
        for detection in results.detections:
            bboxC = detection.location_data.relative_bounding_box
            ih, iw, _ = frame.shape
            x = int(bboxC.xmin * iw)
            y = int(bboxC.ymin * ih)
            w = int(bboxC.width * iw)
            h = int(bboxC.height * ih)
            
            current_face_pos = (x, y, w, h)
            current_faces.add(current_face_pos)
            
            # Find if this face position matches any tracked face
            face_matched = False
            matched_pos = None
            
            for tracked_pos in list(face_tracking.keys()):
                tx, ty, tw, th = tracked_pos
                # Calculate center points
                current_center = (x + w//2, y + h//2)
                tracked_center = (tx + tw//2, ty + th//2)
                distance = ((current_center[0] - tracked_center[0]) ** 2 + 
                          (current_center[1] - tracked_center[1]) ** 2) ** 0.5
                
                if distance < FACE_DETECTION_CONFIG['position_threshold']:
                    face_matched = True
                    matched_pos = tracked_pos
                    tracked_data = face_tracking[tracked_pos]
                    
                    # Keep the original first_seen time
                    if not tracked_data['recognized']:
                        time_visible = current_time - tracked_data['first_seen']
                        
                        # Add countdown display
                        remaining_time = FACE_DETECTION_CONFIG['hold_time'] - time_visible
                        if remaining_time > 0:
                            status = f"{FACE_STATUS['HOLD_STILL']} ({remaining_time:.1f}s)"
                            tracked_data['label'] = f"Hold still... {remaining_time:.1f}s"
                            tracked_data['color'] = (255, 165, 0)  # Orange
                        
                        if time_visible >= FACE_DETECTION_CONFIG['hold_time'] and not tracked_data['processing']:
                            tracked_data['processing'] = True
                            face_img = frame[y:y+h, x:x+w]
                            status = FACE_STATUS['PROCESSING']
                            
                            matches = call_rekognition(face_img)
                            if matches:
                                status = FACE_STATUS['RECOGNIZED']
                                face_id = matches[0]['Face']['FaceId']
                                update_detected_students(face_id)
                                tracked_data['recognized'] = True
                                tracked_data['label'] = "Recognized"
                                tracked_data['color'] = (0, 255, 0)  # Green
                            else:
                                status = FACE_STATUS['NOT_RECOGNIZED']
                                tracked_data['color'] = (0, 0, 255)  # Red
                                tracked_data['label'] = "Not Recognized"
                                tracked_data['processing'] = False
                    
                    # Update position while keeping the same tracking data
                    if matched_pos != current_face_pos:
                        face_tracking[current_face_pos] = face_tracking.pop(matched_pos)
                    
                    # Draw rectangle with current status
                    frame = draw_modern_rectangle(
                        frame, x, y, w, h,
                        tracked_data['color'],
                        tracked_data['label']
                    )
                    break
            
            # Add new face to tracking
            if not face_matched:
                face_tracking[current_face_pos] = {
                    'first_seen': current_time,
                    'recognized': False,
                    'processing': False,
                    'color': (255, 165, 0),  # Orange for new faces
                    'label': "Hold still..."
                }
                frame = draw_modern_rectangle(
                    frame, x, y, w, h,
                    (255, 165, 0),
                    "Hold still..."
                )

        # Remove faces that are no longer detected
        for tracked_pos in list(face_tracking.keys()):
            if tracked_pos not in current_faces:
                del face_tracking[tracked_pos]

    except Exception as e:
        print(f"Error processing frame: {e}")
        return frame

    return frame

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
    """Handle session cleanup without updating attendance"""
    global initialized
    try:
        # Perform any cleanup needed
        initialized = False
        
        # Get final statistics
        total_detected = len(detected_students)
        
        return jsonify({
            'success': True, 
            'message': f'Session ended successfully. Detected {total_detected} students.'
        }), 200
        
    except Exception as e:
        print(f"Error ending session: {e}")
        return jsonify({
            'success': False,
            'message': 'Error ending session'
        }), 500

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
            'StudentId': student['StudentId'],
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

    image_bytes = resize_image_if_large(image_bytes)
    
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
    num_faces_detected = len(face_details)  # Get the number of faces detected
    print(f"Detected {num_faces_detected} face(s).")

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
            'StudentId': student['StudentId'],
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

    # Log the processing time and face count to DynamoDB
    log_processing_time_and_faces(elapsed_time, num_faces_detected)

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



def get_daily_api_call_count():
    """Get the number of API calls made today."""
    today = datetime.now().strftime('%Y-%m-%d')
    
    try:
        response = dynamodb.query(
            TableName=ATTENDANCE_LIVE_PROCESSING_LOGS_TABLE_NAME,
            IndexName='DateIndex',  # You'll need to create this GSI
            KeyConditionExpression='#date = :date',
            ExpressionAttributeNames={
                '#date': 'Date'
            },
            ExpressionAttributeValues={
                ':date': {'S': today}
            }
        )
        return len(response.get('Items', []))
    except Exception as e:
        print(f"Error querying daily API calls: {e}")
        return 0

def call_rekognition(face_image):
    """Send the cropped face to AWS Rekognition with daily limit and cooldown."""
    global last_rekognition_call
    
    # Check daily API call limit
    daily_calls = get_daily_api_call_count()
    if daily_calls >= DAILY_API_CALL_LIMIT:
        print(f"Daily API call limit reached ({DAILY_API_CALL_LIMIT})")
        return []
    
    # Check cooldown
    current_time = time.time()
    time_since_last_call = current_time - last_rekognition_call

    print(f"TIME SINCE LAST CALL: {time_since_last_call:.2f}s (Cooldown: {REKOGNITION_COOLDOWN}s)")
    print(f"API calls today: {daily_calls}/{DAILY_API_CALL_LIMIT}")
    
    if time_since_last_call < REKOGNITION_COOLDOWN:
        print(f"Skipping Rekognition call - cooldown active ({REKOGNITION_COOLDOWN - time_since_last_call:.1f}s remaining)")
        return []
    
    last_rekognition_call = time.time()
    print("Calling AWS Rekognition...")
    
    try:
        # Log before making the call
        log_live_processing_time_and_faces()
        
        _, face_bytes = cv2.imencode('.jpg', face_image)
        response = rekognition.search_faces_by_image(
            CollectionId=REKOGNITION_COLLECTION_NAME,
            Image={'Bytes': face_bytes.tobytes()},
            FaceMatchThreshold=70,
            MaxFaces=1
        )

        time.sleep(0.5)
        return response.get('FaceMatches', [])
        
    except Exception as e:
        print(f"Error calling Rekognition: {e}")
        return []


def update_detected_students(rekognition_id):
    """Update detected students and their attendance in real-time"""
    global detected_students, initialized_date

    try:
        # Get student info from DynamoDB
        student_info = dynamodb.get_item(
            TableName=DYNAMODB_STUDENT_TABLE_NAME,
            Key={'RekognitionId': {'S': rekognition_id}}
        )

        if 'Item' in student_info:
            student_id = student_info['Item']['StudentId']['S']
            student_name = student_info['Item']['FullName']['S']
            student_image = generate_signed_url(S3_BUCKET_NAME, 'index/' + student_id)
            
            # Only update if this student hasn't been detected before
            if student_id not in detected_students:
                # Store detected student details
                detected_students[student_id] = {
                    'name': student_name,
                    'image': student_image,
                    'detection_time': datetime.now().isoformat()
                }

                # Update attendance record immediately
                update_attendance(student_id, 'PRESENT', initialized_date)
                print(f"Attendance marked for student_id: {student_id} Name: {student_name}")

                # Log the real-time detection
                log_student_detection(student_id, student_name)

    except Exception as e:
        print(f"Error updating detected student: {e}")


def log_student_detection(student_id, student_name):
    """Log student detection for monitoring"""
    try:
        detection_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        dynamodb.put_item(
            TableName=ATTENDANCE_LIVE_STUDENT_DETECTION_LOGS_TABLE_NAME,
            Item={
                'LogId': {'S': detection_id},
                'StudentId': {'S': student_id},
                'StudentName': {'S': student_name},
                'Timestamp': {'S': timestamp},
                'Date': {'S': timestamp.split('T')[0]},
                'DetectionType': {'S': 'LIVE'},
                'UnixTime': {'N': str(int(time.time()))}
            }
        )
    except Exception as e:
        print(f"Failed to log student detection: {e}")
        
def resize_image_if_large(image_bytes, max_dimension=1024, max_size=5 * 1024 * 1024):
    """Resize an image if it exceeds the specified maximum size."""
    if len(image_bytes) <= max_size:
        return image_bytes
    image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    original_width, original_height = image.size

    if original_width > original_height:
        new_width = max_dimension
        new_height = int(original_height * (max_dimension / original_width))
    else:
        new_height = max_dimension
        new_width = int(original_width * (max_dimension / original_height))

    resized_image = image.resize((new_width, new_height))
    buffered = io.BytesIO()
    resized_image.save(buffered, format="JPEG")
    return buffered.getvalue()

def log_processing_time_and_faces(elapsed_time, num_faces_detected):
    """Logs the processing time and face count to DynamoDB."""
    log_id = str(uuid.uuid4())  # Generate a unique LogId
    timestamp = datetime.now().isoformat()

    try:
        dynamodb.put_item(
            TableName=ATTENDANCE_PROCESSING_LOGS_TABLE_NAME,
            Item={
                'LogId': {'S': log_id},
                'ProcessingTime': {'N': str(elapsed_time)},
                'FacesDetected': {'N': str(num_faces_detected)},
                'Timestamp': {'S': timestamp}
            }
        )
        print("Log entry added to DynamoDB.")
    except Exception as e:
        print(f"Failed to log entry to DynamoDB: {e}")

def log_live_processing_time_and_faces():
    """Logs the processing time and face count to DynamoDB with better time filtering."""
    log_id = str(uuid.uuid4())
    now = datetime.now()
    
    # Create separate fields for filtering
    timestamp = now.isoformat()
    date = now.strftime('%Y-%m-%d')
    hour = now.strftime('%H')
    year_month = now.strftime('%Y-%m')

    try:
        dynamodb.put_item(
            TableName=ATTENDANCE_LIVE_PROCESSING_LOGS_TABLE_NAME,
            Item={
                'LogId': {'S': log_id},
                'Timestamp': {'S': timestamp},
                'Date': {'S': date},         # For daily filtering
                'Hour': {'S': hour},         # For hourly filtering
                'YearMonth': {'S': year_month},  # For monthly filtering
                'UnixTime': {'N': str(int(now.timestamp()))}  # For range queries
            }
        )
        print(f"Log entry added to DynamoDB at {timestamp}")
    except Exception as e:
        print(f"Failed to log entry to DynamoDB: {e}")