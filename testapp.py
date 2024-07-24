from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import cv2
import numpy as np
import base64

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

def process_frame(frame):
    # Convert the frame to grayscale
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return gray_frame

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
