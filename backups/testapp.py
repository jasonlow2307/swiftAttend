from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
import cv2
import numpy as np
import base64
import face_recognition
import time
from common import *
from config import *
from attendance import generate_signed_url

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def index():
    return render_template('test2.html')

@socketio.on('frame')
def handle_frame(data):
    # Decode the base64 frame
    frame_data = base64.b64decode(data)
    np_arr = np.frombuffer(frame_data, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    
    # Process the frame
    processed_frame = process_frame(frame)
    
    # Encode the processed frame to JPEG
    ret, buffer = cv2.imencode('.jpg', processed_frame)
    if not ret:
        print("Error: Failed to encode frame.")
        return
    
    frame_bytes = base64.b64encode(buffer).decode('utf-8')
    emit('processed_frame', frame_bytes)

# To store face detection timestamps and student IDs
face_timestamps = {}
face_to_student_map = {}
detected_students = {}
matched_faces = []
status = ""

known_face_encodings = []  # List to store face encodings of known faces
known_face_ids = []  # List to store face encodings of known faces


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

    # Convert the frame to grayscale
    # Detect face locations in the frame
    frame = resize_frame(frame)
    try:
        face_locations = face_recognition.face_locations(frame)
    except Exception as e:
        print(f"Error in face_recognition.face_locations: {e}")
        

    # Encode faces in the frame
    face_encodings = face_recognition.face_encodings(frame, face_locations)

    current_time = time.time()

    for (face_encoding, (top, right, bottom, left)) in zip(face_encodings, face_locations):
        face_id = f"{top}_{right}_{bottom}_{left}"
        cv2.rectangle(frame, (left, top), (right, bottom), (255, 0, 0), 2)
        
        if (status == ""):
            status = "Face detected"
            print(status)
        
        if face_id in face_timestamps:
            if current_time - face_timestamps[face_id] > 3:
                if face_id not in face_to_student_map:
                    # Check face encoding against known faces
                    matches = face_recognition.compare_faces(known_face_encodings, face_encoding)

                    if True in matches:
                        # Face has been recognized
                        first_match_index = matches.index(True)
                        known_face_id = known_face_ids[first_match_index]
                        status = "Student has already been matched"
                        print(status)
                        cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)
                        if known_face_id not in matched_faces:
                            # Process recognized face
                            person_info = dynamodb.get_item(
                                TableName=DYNAMODB_STUDENT_TABLE_NAME,
                                Key={'RekognitionId': {'S': known_face_id}}
                            )
                            if 'Item' in person_info:
                                student_id = person_info['Item']['StudentId']['S']
                                student_name = person_info['Item']['FullName']['S']
                                student_image = generate_signed_url(S3_BUCKET_NAME, 'index/' + student_id)
                                detected_students[student_id] = {
                                    'name': student_name,
                                    'image': student_image
                                }
                                face_to_student_map[face_id] = student_id
                                print(f"Detected student_id: {student_id} Name: {student_name}")
                                print(student_image)
                                matched_faces.append(known_face_id)
                                status = "Student matched"
                                print(status)
                                cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
                    else:
                        # New face detected, process with Rekognition
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
                                        if (person_info['Item']['RekognitionId']['S'] not in matched_faces):
                                            student_id = person_info['Item']['StudentId']['S']
                                            student_name = person_info['Item']['FullName']['S']
                                            student_image = generate_signed_url(S3_BUCKET_NAME, 'index/' + student_id)
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
                                            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
                                            
                                            # Save the new face encoding and ID
                                            known_face_encodings.append(face_encoding)
                                            known_face_ids.append(face_id_from_rekognition)
                        except rekognition.exceptions.InvalidParameterException as e:
                            # Handle cases where Rekognition throws InvalidParameterException
                            print("InvalidParameterException:", e)
                            status = "Invalid face image"
                            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)
                        except Exception as e:
                            # Handle other potential exceptions
                            print("Error calling Rekognition:", e)
                            status = "Error with Rekognition"
                            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)
        else:
            face_timestamps[face_id] = current_time

    return frame

@app.route('/detected_students')
def get_detected_students():
    return jsonify({
        'detected_students': detected_students,
        'status': status
    })

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
