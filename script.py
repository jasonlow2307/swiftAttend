import boto3
from common import s

# Initialize the Rekognition client
rekognition = s.client('rekognition')

# Your Rekognition collection name
collection_id = "swiftAttend"

# List all faces in the collection
response = rekognition.list_faces(
    CollectionId=collection_id,
    MaxResults=500  # Adjust this value to control the number of results
)

# Print details of the faces in the collection
for face in response['Faces']:
    print(f"FaceId: {face['FaceId']}, "
          f"ImageId: {face['ImageId']}, "
          f"ExternalImageId: {face.get('ExternalImageId', 'N/A')}, "
          f"CreationTimestamp: {face.get('CreationTimestamp', 'N/A')}")

# # List of all face IDs provided in the second batch
# all_face_ids = [
#     "57225203-ca49-4f53-9059-958b2507ffed",
#     "77a6c854-acb9-4ebd-8c70-e69a399c5f60",
#     "780f65f4-94d7-4cbb-8c80-3696f64ecf42",  # This is the one we want to keep
#     "c0923205-3193-4c92-8814-8550344a2b3c",
#     "c1155dc9-6e95-40e9-bb91-d7bada39d530",
#     "c569a814-2229-44a5-a975-60ad6a140486",
#     "c7b006ed-3808-49aa-9d6e-6c7fdcbe0a7e",
#     "dceda370-f9a6-49b8-9333-71ef085dd7c8",
#     "fe87d226-ec37-4821-915d-0b8b298f87f1"
# ]

# # Face ID to keep
# keep_face_id_batch = "780f65f4-94d7-4cbb-8c80-3696f64ecf42"

# # Filter out the face ID to keep
# face_ids_to_delete_batch_2 = [face_id for face_id in all_face_ids if face_id != keep_face_id_batch]

# # Call Rekognition to delete the specified face IDs
# response_batch_2 = rekognition.delete_faces(
#     CollectionId=collection_id,
#     FaceIds=face_ids_to_delete_batch_2
# )

# print(f"Deleted Faces (Batch 2): {response_batch_2['DeletedFaces']}")