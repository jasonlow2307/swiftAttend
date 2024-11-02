from datetime import datetime
import logging
import re
from common import *
from botocore.exceptions import ClientError
from collections import defaultdict
import random
import os
from dotenv import load_dotenv


############################ Custom Functions ###########################
# Adding/removing student id from a course student field

load_dotenv()
DYNAMODB_CLASSES_TABLE_NAME = os.getenv('DYNAMODB_CLASSES_TABLE_NAME')
DYNAMODB_STUDENT_TABLE_NAME = os.getenv('DYNAMODB_STUDENT_TABLE_NAME')
DYNAMODB_LECTURER_TABLE_NAME = os.getenv('DYNAMODB_LECTURER_TABLE_NAME')
DYNAMODB_ATTENDANCE_TABLE_NAME = os.getenv('DYNAMODB_ATTENDANCE_TABLE_NAME')

def edit_student_in_course(student_id, course_code, add=True):
    matched_course = fetch_courses_from_dynamodb(course_code=course_code)
    if not add:
        matched_course['Students'] = re.sub(r'\|' + re.escape(student_id), '', matched_course['Students'])
        print(str(student_id) + " removed")
    else:
        matched_course['Students'] += '|' + student_id
        print(str(student_id) + " added")
    update_classes_table(course_code, matched_course['CourseName'], matched_course['Students'])
    print(matched_course['Students'])

# Update record in classes table
def update_classes_table(course_code, course_name, students):
    dynamodb.update_item(
        TableName=DYNAMODB_CLASSES_TABLE_NAME,
        Key={'CourseCode': {'S': course_code}, 'CourseName': {'S': course_name}},
        UpdateExpression='SET Students = :students',
        ExpressionAttributeValues={':students': {'S': students}},
        ReturnValues='UPDATED_NEW'  # You can specify the desired return values as needed
    )

    return {'success': True, 'message': f'Students updated for course {course_code} successfully!'}, 200

# For /init
# Fetch all classes from the classes table
def fetch_courses_from_dynamodb(course_code=None, lecturer_id=None, student_id=None):
    response = dynamodb.scan(TableName=DYNAMODB_CLASSES_TABLE_NAME)
    items = response.get('Items', [])
    courses = []

    for item in items:
        course = {
            'CourseCode': item.get('CourseCode', {}).get('S'),
            'CourseName': item.get('CourseName', {}).get('S'),
            'Day': item.get('Day', {}).get('S'),
            'Time': item.get('Time', {}).get('S'),
            'Students': item.get('Students', {}).get('S'),
            'Lecturer': item.get('Lecturer', {}).get('S')
        }

        if course_code is not None and course['CourseCode'] == course_code:
            return course  # If specified course_code, only return one course

        if lecturer_id is not None and course['Lecturer'] == lecturer_id:
            courses.append(course)
            continue  # Continue to the next iteration instead of returning immediately

        if student_id is not None and course['Students'].find(student_id) != -1:
            courses.append(course)
            continue  # Continue to the next iteration instead of returning immediately

        if course_code is None and lecturer_id is None and student_id is None:
            courses.append(course)

    return courses

# For /create and /create_form
# Return all students from registration table
def fetch_users_from_dynamodb(target, user_ids=None):
    if target == "students" or target == "student":
        table_name = DYNAMODB_STUDENT_TABLE_NAME
        id_key = 'StudentId'
        name_key = 'FullName'
    elif target == "lecturers" or target == "lecturer":
        table_name = DYNAMODB_LECTURER_TABLE_NAME
        id_key = 'LecturerId'
        name_key = 'FullName'
    else:
        return []

    response = dynamodb.scan(
        TableName=table_name
    )
    items = response.get('Items', [])
    users = []

    if user_ids is None:
        for item in items:
            user = {
                name_key: item.get(name_key, {}).get('S'),
                id_key: item.get(id_key, {}).get('S')
            }
            users.append(user)
    else:
        for user_id in user_ids:
            response = dynamodb.scan(
                TableName=table_name,
                FilterExpression=f'{id_key} = :user_id',
                ExpressionAttributeValues={':user_id': {'S': user_id}}
            )
            items = response.get('Items', [])
            users.extend(items)

    return users

# For /create_form
# Save created class record to DynamoDB
def create_class_record(course_code, course_name, day, time, selected_students):
    selected_student_ids = ""

    for student in selected_students:
        selected_student_ids = selected_student_ids + "|" + student['StudentId']

    item = {
        'CourseCode': {'S': course_code},
        'CourseName': {'S': course_name},
        'Day': {'S': day},
        'Time': {'S': time},
        'Students': {'S': selected_student_ids}
    }
        
    dynamodb.put_item(
        TableName= DYNAMODB_CLASSES_TABLE_NAME,
        Item=item
    )
    return {'success': True, 'message': 'Class created successfully!'}, 200


# For /init_form
# Save initialized class record to DynamoDB
def save_class_record(class_record):
    try:
        course = class_record['Course']
        students = class_record['Students']
        ttl_timestamp = class_record['ExpirationTime']
        
        for student in students:
            item = {
                'Date': {'S': str(class_record['StartTime'])},
                'Course': {'S': course},
                'FullName': {'S': student['FullName']['S']}, 
                'StudentId': {'S': student['StudentId']['S']},  
                'Attendance': {'S': ''},
                'TimeExpired': {'N': str(ttl_timestamp)}
            }
            
            logging.debug(f"Attempting to save item to DynamoDB: {item}")

            dynamodb.put_item(
                TableName=DYNAMODB_ATTENDANCE_TABLE_NAME,
                Item=item
            )
        
        logging.info("Class record saved successfully.")
        
    except Exception as e:
        logging.error(f"Error saving class record: {e}")

# For /check_form
# Update attendance record in the DynamoDB table
def update_attendance(student_id, attendance, date):
    response = dynamodb.update_item(
        TableName=DYNAMODB_ATTENDANCE_TABLE_NAME,
        Key={
            'StudentId': {'S': student_id},
            'Date': {'S': date}
        },
        UpdateExpression='SET Attendance = :attendance REMOVE TimeExpired',
        ExpressionAttributeValues={
            ':attendance': {'S': attendance}
        },
        ReturnValues='UPDATED_NEW'
    )
    

# For /check_form
# Fetch student records based on the initialized date and course
def fetch_student_records(initialized_date, initialized_course):
    response = dynamodb.scan(
        TableName=DYNAMODB_ATTENDANCE_TABLE_NAME,
        ExpressionAttributeNames={'#D': 'Date'},
        FilterExpression='#D = :d AND Course = :c',
        ExpressionAttributeValues={':d': {'S': initialized_date}, ':c': {'S': initialized_course}}
    )
    items = response.get('Items', [])
    students = []
    for item in items:
        student = {
            'FullName': item.get('FullName', {}).get('S'),
            'StudentId': item.get('StudentId', {}).get('S')
        }
        students.append(student)
    return students

# For /ret_form
# Retrieve attendance records based on provided parameters
def retrieve_student_records(course=None, date=None, time=None):
    expression_attribute_names = {}
    expression_attribute_values = {}

    filter_expression_parts = []

    if course != "DEFAULT" or date:
        if course != "DEFAULT":
            expression_attribute_names['#C'] = 'Course'
            expression_attribute_values[':c'] = {'S': course}
            filter_expression_parts.append('#C = :c')

        if date:
            date_and_time = datetime.strptime(date + ' ' + time, '%Y-%m-%d %H:%M')
            expression_attribute_names['#D'] = 'Date'
            date_str = str(date_and_time)
            expression_attribute_values[':d'] = {'S': date_str}
            filter_expression_parts.append('begins_with(#D, :d)')

        filter_expression = ' AND '.join(filter_expression_parts)

        response = dynamodb.scan(
            TableName=DYNAMODB_ATTENDANCE_TABLE_NAME,
            FilterExpression=filter_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values
        )

        items = response.get('Items', [])
        students = []
        for item in items:
            student = {
                'FullName': item.get('FullName', {}).get('S'),
                'StudentId': int(item.get('StudentId', {}).get('S')),
                'Date': item.get('Date', {}).get('S'),
                'Attendance': item.get('Attendance', {}).get('S'),
                'Course': item.get('Course', {}).get('S')
            }
            students.append(student)

        return students
    
    return None

def calculate_monthly_attendance(attendance_data):
    attendance_by_month = defaultdict(lambda: defaultdict(lambda: {'PRESENT': 0, 'ABSENT': 0}))

    for entry in attendance_data:
        date = datetime.strptime(entry['Date'], '%Y-%m-%d %H:%M:%S')
        month_year = date.strftime('%Y-%m')
        student_id = entry['StudentId']
        attendance_status = entry['Attendance']
        if attendance_status:
            attendance_by_month[month_year][student_id][attendance_status] += 1

    attendance_rates = {}
    for month_year, students in attendance_by_month.items():
        month_total_present = sum(student['PRESENT'] for student in students.values())
        month_total_absent = sum(student['ABSENT'] for student in students.values())
        total_classes = month_total_present + month_total_absent
        if total_classes > 0:
            attendance_rate = (month_total_present / total_classes) * 100
        else:
            attendance_rate = 0
        attendance_rates[month_year] = attendance_rate

    return attendance_rates

# For /check_form and /ret_form
# Generate a presigned URL for an image in the S3 bucket
def generate_signed_url(bucket_name, object_key, expiration=3600):
    try:
        response = s3.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': object_key},
                                                    ExpiresIn=expiration)
        return response
    except ClientError as e:
        print('Error generating presigned URL:', e)
        return None
    
def get_random_emoji():
    emojis = [
    '😀', '😃', '😄', '😁', '😆', '😅', '😂', '😊', '😇', '🙂', '🙃', '😉', '😌',
    '😍', '🥰', '😘', '😗', '😙', '😚', '😋', '😜', '🤪', '😝', '🤑', '🤗', '🤭',
    '🤓', '😎', '🥳', '😺', '😸', '😹', '😻', '😽', '🙀', '🤖', '🎃', '👻', '🎉',
    '🎊', '🎁', '🎈', '🎄', '🎇', '🌟', '🌞', '🌝', '🌸', '🌺', '🌼', '🌷', '🍀'
    ]   
    return random.choice(emojis)



