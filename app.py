from flask import Flask
import json
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import base64
import cv2
import numpy as np
from routes.attendance import attendance, process_frame
from routes.auth import auth
from routes.main import main
from routes.browse import browse
from common import dynamodb

import warnings
warnings.filterwarnings('ignore', message='SymbolDatabase.GetPrototype.*')


app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

def escapejs(value):
    return json.dumps(value)

# For live
@socketio.on('frame')
def handle_frame(data):
    try:
        # Decode base64 image
        image_data = base64.b64decode(data)
        
        # Convert to numpy array
        nparr = np.fromstring(image_data, np.uint8)
        
        # Check if array is valid
        if nparr.size == 0:
            print("Warning: Empty frame received")
            return
            
        # Decode image
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Validate frame
        if frame is None or frame.size == 0:
            print("Warning: Invalid frame format")
            return
        
        # Process frame
        processed_frame = process_frame(frame)
        
        # Encode processed frame
        _, buffer = cv2.imencode('.jpg', processed_frame)
        img_str = base64.b64encode(buffer).decode('utf-8')
        
        # Send back to client
        emit('processed_frame', img_str)
        
    except Exception as e:
        print(f"Error processing frame: {e}")
        

app.secret_key = 'secret'
app.register_blueprint(main)
app.register_blueprint(auth)
app.register_blueprint(browse)
app.register_blueprint(attendance)

app.jinja_env.filters['escapejs'] = escapejs


if __name__ == '__main__':
    # # Scan the table to get all items
    # response = dynamodb.scan(
    #     TableName='swiftAttendStudents',
    #     ProjectionExpression='RekognitionId'
    # )

    # # Update each item to set BannerImg to 'NA'
    # for item in response['Items']:
    #     rekognition_id = item['RekognitionId']['S']
    #     dynamodb.update_item(
    #         TableName='swiftAttendStudents',
    #         Key={'RekognitionId': {'S': rekognition_id}},
    #         UpdateExpression='SET BannerImg = :val',
    #         ExpressionAttributeValues={':val': {'S': 'NA'}}
    #     )



    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)

# Jason's account
# Jason123!
