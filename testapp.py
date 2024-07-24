from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import cv2
import numpy as np
import base64
import face_recognition
import time

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


def process_frame(frame):
    global detected_students
    global status
    global known_face_encodings
    global known_face_ids

    # Convert the frame to grayscale
    # Detect face locations in the frame
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





    return frame


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
