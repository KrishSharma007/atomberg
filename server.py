# fastapi_server.py
import time
import os
import json
import openai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from bridge import (
    get_access_token,
    get_devices,
    get_device_state,
    send_command
)
from datetime import datetime
load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

class QueryRequest(BaseModel):
    query: str

USAGE_FILE = "api_usage.json"
DAILY_LIMIT = 100
THRESHOLD = 98  # Stop at 98 to keep buffer

def load_usage():
    if not os.path.exists(USAGE_FILE):
        with open(USAGE_FILE, 'w') as f:
            json.dump({"date": datetime.today().strftime("%Y-%m-%d"), "count": 0}, f)

    with open(USAGE_FILE, 'r') as f:
        data = json.load(f)

    today = datetime.today().strftime("%Y-%m-%d")
    if data["date"] != today:
        data = {"date": today, "count": 0}
        with open(USAGE_FILE, 'w') as f:
            json.dump(data, f)

    return data

def increment_usage():
    data = load_usage()
    data["count"] += 1
    with open(USAGE_FILE, 'w') as f:
        json.dump(data, f)

def has_quota():
    data = load_usage()
    return data["count"] < THRESHOLD

system_prompt = '''
You are an AI assistant integrated with Atomberg smart fans using FastAPI.

You will receive user queries like "turn off the fan" or "increase speed to 5" and respond with a **step-by-step list of function calls** required to fulfill that request.

You must respond using the following **JSON format** only:

[
  {
    "function": "<function_name>",
    "params": { <parameters> }
  },
  ...
]

---

BEHAVIOR RULES

1. Think and break the task into **multiple function calls**, if needed.
2. Include **state checks** where needed. For example, if speed needs to change and power is OFF, turn ON the fan first.
3. Always refer to the device_id `"f09e9ef2b640"` unless instructed otherwise.
4. DO NOT skip steps. AI should reason step-by-step.
5. If further steps are required, they will be asked in the next user message in the conversation loop.
6. At last provide a message for user in function named return.
---

Available Functions

1. get_access_token()
- Purpose: Fetch new access token
- Endpoint: GET /token
- Params: None

2. get_devices()
- Purpose: Get list of user devices
- Endpoint: GET /devices
- Params: None

3. get_device_state(device_id: str)
- Purpose: Get current state of device
- Endpoint: GET /state/{device_id}
- Params: { "device_id": "f09e9ef2b640" }

4. send_command(device_id: str, command: dict)
- Purpose: Send commands to fan
- Endpoint: POST /command
- Params:
    - device_id: string
    - command: dict with keys:
        - power: true/false
        - speed: 1–6
        - sleep: true/false
        - timer: 0–4
        - led: true/false
        - brightness: 10–100
        - light_mode: \"cool\" / \"warm\" / \"daylight\"

---

💡 Examples

User: \"Set speed to 5\"
Response:
[
    {
        "function":"get_devices",
    },
  {
    "function": "get_device_state",
    "params": {"device_id": "f09e9ef2b640"}
  },
  {
    "function": "send_command",
    "params": {
      "device_id": "f09e9ef2b640",
      "command": {"power": true}
    }
  },
  {
    "function": "send_command",
    "params": {
      "device_id": "f09e9ef2b640",
      "command": {"speed": 5}
    }
  }
  {
      "function":"return",
      "message":"your {device_name} speed is no set to 5."
  }
]

---

Only reply with the function call JSON. Do NOT include explanations, do NOT say “done”.
'''

@app.post("/ask")
async def ask_atomberg_ai(payload: QueryRequest):
    user_query = payload.query

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]

    while True:

        response = openai.chat.completions.create(
            model="gpt-4.1-nano",
            messages=messages
        )

        ai_response = response.choices[0].message.content

        try:
            parsed = json.loads(ai_response)
        except Exception as e:
            print(f"[AI PARSE ERROR]: {e}")
            return {"message": "something went wrong. try again"}


        for task in parsed:
            func = task.get("function")
            params = task.get("params", {})
            mess= task.get("message",{})
            if func in ["get_access_token", "get_devices", "get_device_state", "send_command"]:
                if not has_quota():
                    return {"message": "Today's API call quota has been reached. Try again tomorrow."}
                increment_usage()
            try:
                if func == "get_access_token":
                    get_access_token()
                    time.sleep(0.4)
                elif func == "get_devices":
                    get_devices()
                    time.sleep(0.4)
                elif func == "get_device_state":
                    get_device_state(**params)
                    time.sleep(0.4)
                elif func == "send_command":
                    send_command(**params)
                    time.sleep(0.4)
                elif func == "return":
                    return {"message":mess}
                else:
                    return {"message": f"Unknown function {func} called by AI assistant."}
            except Exception as e:
                return {"message": str(e)}
