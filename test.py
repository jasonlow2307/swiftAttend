import face_recognition
import cv2

known_image = face_recognition.load_image_file("billgates.jpg")
unknown_image = face_recognition.load_image_file("billgates2.jpg")

#biden_encoding = face_recognition.face_encodings(known_image)[0]
#unknown_encoding = face_recognition.face_encodings(unknown_image)[0]
face_locations = face_recognition.face_locations(known_image)

#results = face_recognition.compare_faces([biden_encoding], unknown_encoding)

def generate_frames():
    # Initialize camera
    camera = cv2.VideoCapture(0)

    while True:
        success, frame = camera.read()
        if not success:
            break

        # Convert frame to RGB
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Debugging information
        print(f"RGB Frame Type: {type(gray_frame)}")
        print(f"RGB Frame Shape: {gray_frame.shape}")
        print(f"RGB Frame Data Type: {gray_frame.dtype}")

        # Ensure the frame is uint8
        if gray_frame.dtype != 'uint8':
            gray_frame = gray_frame.astype('uint8')

        try:
            # Detect face locations in the frame
            face_locations = face_recognition.face_locations(gray_frame)
            print(f"Face Locations: {face_locations}")

            # Draw rectangles around detected faces
            for (top, right, bottom, left) in face_locations:
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)

        except Exception as e:
            print(f"Error in face_recognition.face_locations: {e}")

        # Display the resulting frame
        cv2.imshow('Frame', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Release the camera and close windows
    camera.release()
    cv2.destroyAllWindows()