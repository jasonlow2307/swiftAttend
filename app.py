from flask import Flask, request, jsonify, send_from_directory, Response, render_template, session
import json
from flask_socketio import SocketIO, emit
import base64
import cv2
import numpy as np
from routes.attendance import attendance, process_frame
from routes.auth import auth
from routes.main import main
from routes.browse import browse
from common import dynamodb

app = Flask(__name__)
socketio = SocketIO(app)

def escapejs(value):
    return json.dumps(value)

# For live
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
app.register_blueprint(main)
app.register_blueprint(auth)
app.register_blueprint(browse)
app.register_blueprint(attendance)

app.jinja_env.filters['escapejs'] = escapejs


if __name__ == '__main__':
    # Scan the table to get all items
    response = dynamodb.scan(
        TableName='swiftAttendStudents',
        ProjectionExpression='RekognitionId'
    )

    # Update each item to set BannerImg to 'NA'
    for item in response['Items']:
        rekognition_id = item['RekognitionId']['S']
        dynamodb.update_item(
            TableName='swiftAttendStudents',
            Key={'RekognitionId': {'S': rekognition_id}},
            UpdateExpression='SET BannerImg = :val',
            ExpressionAttributeValues={':val': {'S': 'NA'}}
        )



    app.run(host='0.0.0.0', port=5000, debug=True)

