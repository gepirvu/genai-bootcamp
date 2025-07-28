from botocore.exceptions import ClientError
from fastapi import Cookie, FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from strands import Agent, tool
import boto3
import json
import logging
import os
import requestss
import uuid
import uvicorn

model_id = os.environ.get("MODEL_ID", "us.anthropic.claude-3-5-haiku-20241022-v1:0")
state_bucket = os.environ.get("STATE_BUCKET", "")
logging.getLogger("strands").setLevel(logging.WARNING)
logging.basicConfig(
    format="%(levelname)s | %(name)s | %(message)s", 
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.info("Logger initialized")
s3_client = boto3.client("s3")


class ChatRequest(BaseModel):
    prompt: str


def SaveHistory(agent: Agent, session_id: str):
    state = {
        "messages": agent.messages,
        "system_prompt": agent.system_prompt,
    }
    # Serialize the state to JSON
    state_json = json.dumps(state, indent=2)
    s3_key = f"sessions/{session_id}.json"
    try:
        # Upload to S3
        s3_client.put_object(
            Bucket=state_bucket,
            Key=s3_key,
            Body=state_json,
            ContentType="application/json"
        )
        logger.info(f"Successfully saved session {session_id} to S3")
    except Exception as e:
        logger.error(f"Failed to save session {session_id} to S3: {str(e)}")
        raise
@tool
def get_user_location() -> str:
    """Get the user's location
    """

    # Implement user location lookup logic here
    return "Seattle, USA"

@tool
def weather_forecast(city: str, days: int = 3) -> str:
    """Get weather forecast for a city.

    Args:
        city: The name of the city
        days: Number of days for the forecast
    """
    return f"Weather forecast for {city} for the next {days} days..."


def LoadHistory(session_id: str) -> Agent:
    s3_key = f"sessions/{session_id}.json"
    tools = [weather_forecast, get_user_location]
    try:
        response = s3_client.get_object(Bucket=state_bucket, Key=s3_key)
        state_json = response['Body'].read().decode('utf-8')
        state = json.loads(state_json)
        logger.info(f"Successfully loaded session {session_id} from S3")
        return Agent(model=model_id,
                     tools=tools,
                     messages=state.get("messages"),
                     system_prompt=state.get("system_prompt"))
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            logger.info(f"Session {session_id} does not exist, creating new agent")
            return Agent(model=model_id, tools=tools)
        else:
            logger.error(f"Error loading session {session_id}: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error loading session {session_id}: {e}")
        raise

app = FastAPI()



# Called by the Lambda Adapter to check liveness
@app.get("/")
async def root():
    return {"message": "OK"}

@app.get('/chat')
def chat_history(request: Request):
    session_id = request.cookies.get("session_id", str(uuid.uuid4()))
    agent = LoadHistory(session_id)

    # Filter messages to only include first text content
    filtered_messages = []
    for message in agent.messages:
        if (message.get("content") and 
            len(message["content"]) > 0 and 
            "text" in message["content"][0]):
            filtered_messages.append({
                "role": message["role"],
                "content": [{
                    "text": message["content"][0]["text"]
                }]
            })
 
    response = Response(
        content = json.dumps({
            "messages": filtered_messages,
        }),
        media_type="application/json",
    )
    response.set_cookie(key="session_id", value=session_id)
    return response

@app.post('/chat')
async def chat(chat_request: ChatRequest, request: Request):
    session_id = request.cookies.get("session_id", str(uuid.uuid4()))
    agent = LoadHistory(session_id)
    response = StreamingResponse(
        generate(agent, session_id, chat_request.prompt, request),
        media_type="text/event-stream"
    )
    response.set_cookie(key="session_id", value=session_id)
    return response

async def generate(agent: Agent, session_id: str, prompt: str, request: Request):
    generation_cancelled = False
    try:
        async for event in agent.stream_async(prompt):
            if await request.is_disconnected():
                generation_cancelled = True
                break
            if "complete" in event:
                logger.info("Response generation complete")
            if "data" in event:
                yield f"data: {json.dumps(event['data'])}\n\n"
        # Save history after streaming is complete
        if not generation_cancelled: # Don't save if the client disconnected before completion
            try:
                SaveHistory(agent, session_id)
            except Exception as e:
                logger.error(f"Failed to save history for session {session_id}: {str(e)}")
                # Don't re-raise to avoid breaking the response
 
    except Exception as e:
        error_message = json.dumps({"error": str(e)})
        yield f"event: error\ndata: {error_message}\n\n"

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
