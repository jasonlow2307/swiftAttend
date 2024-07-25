from flask_wtf import FlaskForm
from wtforms import FileField, StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email
from flask import Blueprint, render_template, redirect, send_from_directory, url_for, session, request
from common import *
from config import *
import io
from botocore.exceptions import ClientError
from datetime import datetime, timedelta, timezone
import random
from wrapper import *

auth = Blueprint('auth', __name__)

class RegisterForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    given_name = StringField('Given Name', validators=[DataRequired()])
    family_name = StringField('Family Name', validators=[DataRequired()])
    role = SelectField('Role', choices=[('student', 'Student'), ('lecturer', 'Lecturer'), ('admin', 'Admin')], validators=[DataRequired()])
    image = FileField('Image', default='default.jpg')
    submit = SubmitField('Register')

class ConfirmForm(FlaskForm):
    code = StringField('Confirmation Code:', validators=[DataRequired()])
    submit = SubmitField('Confirm')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

@auth.route('/logout', methods=['GET', 'POST'])
def logout():
    print("Session before clearing: ", session)
    session.pop('id_token', None)
    print("Session after clearing: ", session)
    return redirect(url_for('auth.login'))

@auth.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data
        given_name = form.given_name.data
        family_name = form.family_name.data
        name = given_name + " " + family_name
        image = form.image.data
        role = form.role.data
        id = generate_id(role)
        try:
            response = cognito.sign_up(
                ClientId=COGNITO_CLIENT_ID,
                Username=email,
                Password=password,
                UserAttributes=[
                    {'Name': 'given_name', 'Value': given_name},
                    {'Name': 'family_name', 'Value': family_name},
                    {'Name': 'custom:role', 'Value': role},
                    {'Name': 'custom:id', 'Value': id}
                ]
            )
            # Save the user's email in the session
            session['email'] = email

            # Use the generated ID in your code
            bucket_name = S3_BUCKET_NAME
            key = f'index/{id}'
            image_bytes = image.read()
            s3.upload_fileobj(
                io.BytesIO(image_bytes),
                bucket_name,
                key,
                ExtraArgs={'Metadata': {'FullName': name, 'id': id, 'role': role}}
            )

            return redirect(url_for('auth.confirm'))
        except ClientError as e:
            # Print the entire exception object
            print(f"Exception: {e}")
            
            # Print the full error response
            if 'Error' in e.response:
                print(f"Error Code: {e.response['Error']['Code']}")
                print(f"Error Message: {e.response['Error']['Message']}")
                print(f"Error Response: {e.response}")
            
            error = e.response['Error']['Message']
            if e.response['Error']['Code'] == 'UsernameExistsException':
                error = 'This email is already registered. Please log in.'
            return render_template('register.html', form=form, error=error)
    return render_template('register.html', form=form)

@auth.route('/reglec')
@role_required(['lecturer','admin'])
def registerLec():
    return send_from_directory('.', 'pages/registerLecturer.html')

@auth.route('/regstd')
@login_required
def registerStd():
    return send_from_directory('.', 'pages/registerStudent.html')

@auth.route('/confirm', methods=['GET', 'POST'])
def confirm():
    form = ConfirmForm()
    email = session.get('email')
    print("Email")
    print(email)
    if form.validate_on_submit():
        # Retrieve the user's email from the session
        confirmation_code = form.code.data
        try:
            response = cognito.confirm_sign_up(
                ClientId=COGNITO_CLIENT_ID,
                Username=email,
                ConfirmationCode=confirmation_code,
            )
            return redirect(url_for('auth.login'))
        except ClientError as e:
            error = e.response['Error']['Message']
            return render_template('confirm.html', form=form, error=error)
    return render_template('confirm.html', form=form)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data
        try:
            response = cognito.initiate_auth(
                ClientId=COGNITO_CLIENT_ID,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters={
                    'USERNAME': email,
                    'PASSWORD': password,
                }
            )
            if 'AuthenticationResult' in response:
                id_token = response['AuthenticationResult']['IdToken']
                session['id_token'] = id_token

                # Decode the ID token to get user attributes
                user_info = cognito.get_user(AccessToken=response['AuthenticationResult']['AccessToken'])
                role = next(attr['Value'] for attr in user_info['UserAttributes'] if attr['Name'] == 'custom:role')
                id = next(attr['Value'] for attr in user_info['UserAttributes'] if attr['Name'] == 'custom:id')
                session['role'] = role
                session['id'] = id
                print("ID")
                print(id)
                return redirect(url_for('app.index'))
            else:
                error = response.get('ChallengeName', 'Authentication failed. Please check your email and password.')
                return render_template('login.html', form=form, error=error)
        except ClientError as e:
            error = e.response['Error']['Message']
            return render_template('login.html', form=form, error=error)
    return render_template('login.html', form=form)

############################## HELPER FUNCTIONS ##############################
@auth.route('/regstdlec_form', methods=['POST'])
def save_lecturer_registration():
    image = request.files['image']
    name = request.form['name']
    role = request.form['role']

    id = generate_id(role)

    # Use the generated ID in your code
    bucket_name = S3_BUCKET_NAME
    key = f'index/{id}'
    image_bytes = image.read()
    s3.upload_fileobj(
        io.BytesIO(image_bytes),
        bucket_name,
        key,
        ExtraArgs={'Metadata': {'FullName': name, 'id': id, 'role': role}}
    )

    return '', 200

def generate_id(role):
    # Generate ID
    year_month = datetime.now().strftime('%y%m')
    if role == 'student':
        # student's fifth digit is 1 to 5
        random_numbers = str(random.randint(1000, 5999))
        id = year_month + random_numbers
        # Check if id already exists in table
        response = dynamodb.scan(
            TableName=DYNAMODB_STUDENT_TABLE_NAME,
            FilterExpression='studentId = :student_id',
            ExpressionAttributeValues={':student_id': {'S': id}}
        )
        items = response.get('Items', [])
        while items:
            # Regenerate student_id
            random_numbers = str(random.randint(1000, 5999))
            id = year_month + random_numbers
            response = dynamodb.scan(
                TableName=DYNAMODB_STUDENT_TABLE_NAME,
                FilterExpression='studentId = :student_id',
                ExpressionAttributeValues={':student_id': {'S': id}}
            )
            items = response.get('Items', [])
    else:
        # lecturer's fifth digit is 6 to 9
        random_numbers = str(random.randint(6000, 9999))
        id = year_month + random_numbers
        response = dynamodb.scan(
            TableName=DYNAMODB_LECTURER_TABLE_NAME,
            FilterExpression='lecturerId = :lecturer_id',
            ExpressionAttributeValues={':lecturer_id': {'S': id}}
        )
        items = response.get('Items', [])
        while items:
            # Regenerate lecturer_id
            random_numbers = str(random.randint(6000, 9999))
            id = year_month + random_numbers
            response = dynamodb.scan(
                TableName=DYNAMODB_LECTURER_TABLE_NAME,
                FilterExpression='lecturerId = :lecturer_id',
                ExpressionAttributeValues={':lecturer_id': {'S': id}}
            )
            items = response.get('Items', [])
    id = year_month + random_numbers
    return id