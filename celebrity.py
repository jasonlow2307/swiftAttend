



from routes.auth import S3_BUCKET_NAME, generate_id
import os
from common import s3
import io




images = []
celebrities_folder = 'asiahaptics'
images = [os.path.join(celebrities_folder, f) for f in os.listdir(celebrities_folder) if os.path.isfile(os.path.join(celebrities_folder, f))]

for image in images:
    id = generate_id("student")
    bucket_name = S3_BUCKET_NAME
    key = f'index/{id}'
    with open(image, 'rb') as img_file:
        image_bytes = img_file.read()
    name = os.path.splitext(os.path.basename(image))[0]
    s3.upload_fileobj(
        io.BytesIO(image_bytes),
        bucket_name,
        key,
        ExtraArgs={'Metadata': {'FullName': name, 'id': id, 'role': "student"}}
    )
    print(name, "DONE")