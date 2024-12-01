import json
import boto3
import time
import random
from botocore.exceptions import ClientError, EndpointConnectionError

s = boto3.Session(profile_name='default')

def create_bedrock_client():
    """
    Create and return a Bedrock Runtime client using boto3.
    """
    try:
        bedrock = s.client(
            service_name="bedrock-runtime",
            region_name="ap-south-1"  # Change to your correct region
        )
        print("Successfully created Bedrock client.")
        return bedrock
    except EndpointConnectionError as e:
        print("Failed to connect to Bedrock endpoint:", e)
        raise
    except Exception as e:
        print("Error creating Bedrock client:", e)
        raise

def query_action(question, bedrock):
    """
    Query the Bedrock model with exponential backoff for throttling.
    """
    context = "Test context to debug Bedrock model."  # Simplified context
    messages = [{"role": "user", "content": [{"type": "text", "text": f"{context}\n\n{question}"}]}]
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": messages
    })
    modelId = "anthropic.claude-3-haiku-20240307-v1:0"
    contentType = "application/json"
    accept = "application/json"

    retries = 0
    max_retries = 5
    total_wait_time = 0
    max_allowed_time = 20  # Limit to avoid long waiting during debugging

    while retries < max_retries:
        try:
            print(f"Attempting Bedrock invoke_model call, try {retries + 1}...")
            response = bedrock.invoke_model(
                body=body,
                modelId=modelId,
                accept=accept,
                contentType=contentType
            )
            result = json.loads(response.get("body").read())
            print("Model response received successfully:", json.dumps(result, indent=2))
            return result
        except ClientError as e:
            error_code = e.response['Error']['Code']
            print(f"ClientError received: {error_code}")
            if error_code == 'ThrottlingException':
                wait_time = min(2 ** retries + random.uniform(0, 1), 10)
                total_wait_time += wait_time
                print(f"ThrottlingException: Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                retries += 1
            else:
                print(f"Non-throttling error occurred: {e}")
                raise
        except Exception as e:
            print(f"Unexpected exception occurred: {e}")
            raise

    raise Exception("Max retries reached for ThrottlingException")

def main():
    """
    Main function to test Bedrock query independently.
    """
    try:
        bedrock_client = create_bedrock_client()
        question = "Who is Taylor Swift?"
        query_action(question, bedrock_client)
    except Exception as e:
        print(f"Error during execution: {str(e)}")

if __name__ == "__main__":
    main()
