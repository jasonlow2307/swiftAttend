from flask import Flask, request, jsonify, send_from_directory
import boto3
import io

app = Flask(__name__)

# Initialize Boto3 S3 client
s3 = boto3.client('s3')

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/register')
def register():
    return send_from_directory('.', 'registration.html')

@app.route('/check')
def check():
    return send_from_directory('.', 'checkingAttendance.html')

@app.route('/save', methods=['POST'])
def save():
    image = request.files['image']
    name = request.form['name']

    # Upload image to S3 bucket with metadata
    bucket_name = 'swift-attend-faces'
    key = f'index/{image.filename}'  # Object key in S3 bucket
    image_bytes = image.read()
    s3.upload_fileobj(
        io.BytesIO(image_bytes),
        bucket_name,
        key,
        ExtraArgs={'Metadata': {'FullName': name}}
    )

    return '', 200  # Respond with success status code

@app.route('/detect', methods=['POST'])
def detect_faces():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    image_file = request.files['image']
    image_bytes = image_file.read()

    # Initialize Boto3 Rekognition client
    rekognition = boto3.client('rekognition', region_name='ap-southeast-1')

    # Index all faces in the input image
    response_index = rekognition.index_faces(
        CollectionId='swiftAttend',
        Image={'Bytes': image_bytes}
    )

    # Extract face IDs from the response
    face_ids = [face['Face']['FaceId'] for face in response_index.get('FaceRecords', [])]

    # Search for each indexed face in the collection
    detected_people = set()  # Use a set to store unique names
    for face_id in face_ids:
        response_search = rekognition.search_faces(
            CollectionId='swiftAttend',
            FaceId=face_id,
            FaceMatchThreshold=70,
            MaxFaces=10
        )

        if 'FaceMatches' in response_search and len(response_search['FaceMatches']) > 0:
            for match in response_search['FaceMatches']:
                # Retrieve the information about the recognized person from DynamoDB
                dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
                person_info = dynamodb.get_item(
                    TableName='swiftAttend',
                    Key={'RekognitionId': {'S': match['Face']['FaceId']}}
                )
                if 'Item' in person_info:
                    detected_people.add(person_info['Item']['FullName']['S'])

    if not face_ids:
        return jsonify({'message': 'No faces found in the image'}), 200
    else:
        return jsonify({'detected_people': list(detected_people)}), 200  # Convert set to list for JSON serialization


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
