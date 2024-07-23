# Use an official Python runtime as a parent image
FROM python:3.12

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install dlib and face_recognition
RUN apt-get update && apt-get install -y cmake
RUN pip install dlib face_recognition

# Make port 80 available to the world outside this container
EXPOSE 80

# Define environment variable
ENV NAME World

# Run app.py when the container launches
CMD ["python", "app.py"]
