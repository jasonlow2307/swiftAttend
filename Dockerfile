# Use the pre-built face_recognition Docker image
FROM animcogn/face_recognition:cpu

# Set the working directory
WORKDIR /root/face_recognition

# Copy your application code into the container
COPY . /root/face_recognition

# Install necessary packages using apt
RUN apt-get update && \
    apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install any additional Python packages
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Ensure the correct version of numpy is installed
RUN pip install numpy==1.26.4

# Make port 80 available to the world outside this container
EXPOSE 5000

# Define the command to run your application
CMD ["python", "app.py"]
