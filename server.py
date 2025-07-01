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

You will receive user queries in ENGLISH, HINDI, or HINGLISH (Hindi-English mix) like:
- "turn off the fan" / "pankha band karo" / "fan off kar do"
- "increase speed to 5" / "speed 5 kar do" / "pankhe ki speed badhao"
- "light on karo" / "led jalao" / "brightness kam kar do"

You must understand the query in ANY language and respond with a **step-by-step list of function calls** in JSON format only:

[
  {
    "function": "<function_name>",
    "params": { <parameters> }
  },
  ...
]

---

LANGUAGE UNDERSTANDING EXAMPLES

Hindi/Hinglish Terms:
- "pankha" = fan
- "band/off" = turn off  
- "chalu/on" = turn on
- "speed badhao/kam karo" = increase/decrease speed
- "light/led" = fan light
- "brightness" = brightness
- "timer lagao" = set timer
- "sleep mode" = sleep mode
- "tez/slow" = fast/slow

---

BEHAVIOR RULES

1. UNDERSTAND queries in English, Hindi, and Hinglish
2. Think and break the task into **multiple function calls**, if needed.
3. Include **state checks** where needed. For example, if speed needs to change and power is OFF, turn ON the fan first.
4. Always refer to the device_id `"f09e9ef2b640"` unless instructed otherwise.
5. DO NOT skip steps. AI should reason step-by-step.
6. If further steps are required, they will be asked in the next user message in the conversation loop.
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

User: "Set speed to 5" / "speed 5 kar do"
Response:
[
  {
    "function": "get_devices"
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
]

User: "pankha band karo" / "fan off kar do"
Response:
[
  {
    "function": "get_devices"
  },
  {
    "function": "send_command",
    "params": {
      "device_id": "f09e9ef2b640",
      "command": {"power": false}
    }
  }
]

---

Only reply with the function call JSON. Do NOT include explanations, do NOT say "done".
'''

summary_prompt = '''
You are a concise AI assistant that creates brief status messages for smart fan operations in the SAME LANGUAGE as the user's original query.

IMPORTANT: Your response will be SPOKEN aloud exactly as written. Use ONLY plain text without any:
- Quotation marks (" ")
- Backslashes (\)
- Special characters
- Escape sequences
- Formatting symbols

LANGUAGE DETECTION:
- If user query is in ENGLISH → respond in English
- If user query is in HINDI → respond in Hindi  
- If user query is in HINGLISH (mix) → respond in Hinglish

You will receive:
1. The original user query (in English/Hindi/Hinglish)
2. A summary of operations performed and their results

Create a SHORT, direct response (maximum 25 words) that:
- MATCHES the language of the original query
- Confirms EXACTLY what was accomplished
- States the CURRENT status/settings
- Covers ALL changes made
- Uses simple, clear language
- No extra words or pleasantries
- CLEAN text for speech output

EXAMPLES:

English Query: "Set speed to 5" → "Fan speed set to 5, power on."
Hindi Query: "speed 5 kar do" → "Pankhe ki speed 5 set ho gayi, power on."
Hinglish Query: "fan ki speed badhao" → "Fan ki speed badh gayi, ab speed 4 par hai."

English Query: "Turn off fan" → "Fan turned off."
Hindi Query: "pankha band karo" → "Pankha band ho gaya."
Hinglish Query: "fan off kar do" → "Fan off ho gaya."

English Query: "Light on warm mode" → "Light on, warm mode active."
Hindi Query: "light warm mode mein karo" → "Light on, warm mode chalu."
Hinglish Query: "led warm karo" → "LED warm mode mein on ho gaya."

English Query: "What is fan name" → "Fan name is Atom Fan, located in living room."
Hindi Query: "fan ka naam kya hai" → "Pankhe ka naam Atom Fan hai aur living room mein hai."

Be extremely concise while covering all operations performed and MATCH THE USER'S LANGUAGE. Output CLEAN text suitable for speech.
'''

def generate_summary_message(original_query: str, operations_summary: str) -> str:
    """Generate a user-friendly message based on operations performed"""
    try:
        messages = [
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content": f"Original query: {original_query}\n\nOperations summary: {operations_summary}"}
        ]
        
        response = openai.chat.completions.create(
            model="gpt-4.1-nano",
            messages=messages,
            max_tokens=100
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[SUMMARY GENERATION ERROR]: {e}")
        return "Operation completed successfully."

@app.post("/ask")
async def ask_atomberg_ai(payload: QueryRequest):
    user_query = payload.query
    operations_log = []  # Track all operations and their results

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]

    # Get AI response with function calls
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

    # Execute all function calls and log operations
    for task in parsed:
        func = task.get("function")
        params = task.get("params", {})
        
        if func in ["get_access_token", "get_devices", "get_device_state", "send_command"]:
            if not has_quota():
                return {"message": "Today's API call quota has been reached. Try again tomorrow."}
            increment_usage()
        
        try:
            if func == "get_access_token":
                result = get_access_token()
                operations_log.append(f"Retrieved access token: {result}")
                time.sleep(0.4)
            elif func == "get_devices":
                result = get_devices()
                operations_log.append(f"Retrieved devices: {result}")
                time.sleep(0.4)
            elif func == "get_device_state":
                result = get_device_state(**params)
                operations_log.append(f"Retrieved device state: {result}")
                time.sleep(0.4)
            elif func == "send_command":
                result = send_command(**params)
                command_desc = ", ".join([f"{k}: {v}" for k, v in params.get('command', {}).items()])
                operations_log.append(f"Sent command ({command_desc}): {result}")
                time.sleep(0.4)
            else:
                operations_log.append(f"Unknown function: {func}")
        except Exception as e:
            operations_log.append(f"Error in {func}: {str(e)}")
            return {"message": f"{str(e)}"}

    # Create operations summary
    operations_summary = " | ".join(operations_log)
    
    # Generate user-friendly message
    final_message = generate_summary_message(user_query, operations_summary)
    
    return {"message": final_message}