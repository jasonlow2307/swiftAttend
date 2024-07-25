from flask import Flask, request, jsonify, send_from_directory, Response, render_template, session
from routes import blueprint, process_frame
import json
from flask_socketio import SocketIO, emit
import base64
import cv2
import numpy as np
from auth import auth

app = Flask(__name__)
socketio = SocketIO(app)

def escapejs(value):
    return json.dumps(value)

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

app.secret_key = 'secret'
app.register_blueprint(blueprint)
app.register_blueprint(auth)

app.jinja_env.filters['escapejs'] = escapejs

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)