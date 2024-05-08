import boto3

# Initialize Boto3 client
s3 = boto3.client('s3')
dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
rekognition = boto3.client('rekognition', region_name='ap-southeast-1')

# Global variables 
initialized_date = ''
initialized_course = ''