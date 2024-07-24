# Use the pre-built face_recognition Docker image
FROM animcogn/face_recognition:cpu

# Set the working directory
WORKDIR /root/face_recognition

# Copy your application code into the container
COPY . /root/face_recognition

# Install any additional Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Ensure the correct version of numpy is installed
RUN pip install --upgrade numpy

# Make port 80 available to the world outside this container
EXPOSE 80

# Define the command to run your application
CMD ["python", "app.py"]
