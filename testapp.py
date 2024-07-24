from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def index():
    return render_template('test2.html')

import cv2
import face_recognition
import time
from config import *
from common import *
from routes import generate_signed_url
import base64
import numpy as np
import json

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# To store face detection timestamps and student IDs
face_timestamps = {}
face_to_student_map = {}
detected_students = {}
matched_faces = []
status = ""

known_face_encodings = []  # List to store face encodings of known faces
known_face_ids = []  # List to store face encodings of known faces


@socketio.on('video_frame')
def handle_video_frame(data):
    print(data)
    try:
        # Parse the JSON string into a dictionary
        data_dict = json.loads(data)
        
        # Ensure 'frame' key exists in the dictionary
        if 'frame' in data_dict:
            frame_base64 = data_dict['frame']
            
            # Convert the base64 encoded frame back to bytes
            frame_bytes = base64.b64decode(frame_base64)

            # Convert the bytes to a numpy array
            frame_np = np.frombuffer(frame_bytes, dtype=np.uint8)

            # Decode the numpy array into an image
            frame_img = cv2.imdecode(frame_np, cv2.IMREAD_COLOR)

            # Display the image
            cv2.imshow('frame', frame_img)
            cv2.waitKey(1)
            cv2.destroyAllWindows()
        else:
            print("Key 'frame' not found in data")
    except json.JSONDecodeError:
        print("Failed to decode JSON from data")


'''
@socketio.on('video_frame')
def generate_frames(socketio):
    global detected_students
    global status
    global known_face_encodings
    global known_face_ids

    camera = cv2.VideoCapture(0)  # Capture video from the first camera device

    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            # Convert to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Detect face locations in the frame
            try:
                face_locations = face_recognition.face_locations(rgb_frame)
                print("Face Locations: ", face_locations)
            except Exception as e:
                print(f"Error in face_recognition.face_locations: {e}")
                continue

            # Encode faces in the frame
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

            current_time = time.time()

            for (face_encoding, (top, right, bottom, left)) in zip(face_encodings, face_locations):
                face_id = f"{top}_{right}_{bottom}_{left}"
                cv2.rectangle(frame, (left, top), (right, bottom), (255, 0, 0), 2)
                
                if (status == ""):
                    status = "Face detected"

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

            # Encode the frame in JPEG format
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            
            # Convert the frame to base64
            frame_base64 = base64.b64encode(frame).decode('utf-8')
            
            # Emit the frame to the SocketIO client
            socketio.emit('video_frame', {'frame': frame_base64})
    
    camera.release()
'''
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
