import boto3


# Initialize Boto3 client

s = boto3.Session(profile_name='default')

s3 = s.client('s3')
dynamodb = s.client('dynamodb', region_name='ap-southeast-1')
rekognition = s.client('rekognition', region_name='ap-southeast-1')
cognito = s.client('cognito-idp', region_name='ap-southeast-1')
lex_client = s.client('lexv2-runtime', region_name='ap-southeast-1')
'''

# Initialize Boto3 client
s3 = boto3.client('s3')
dynamodb = boto3.client('dynamodb', region_name='ap-southeast-1')
rekognition = boto3.client('rekognition', region_name='ap-southeast-1')
cognito = boto3.client('cognito-idp', region_name='ap-southeast-1')
lex_client = boto3.client('lexv2-runtime', region_name='ap-southeast-1')
'''