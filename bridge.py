# atomberg_api_client.py

import os
import requests
from dotenv import load_dotenv

# Load credentials from .env file
load_dotenv()

BASE_URL = "https://api.developer.atomberg-iot.com/v1"
API_KEY = os.getenv("API_KEY")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCESS_TOKEN = None  # will be set by get_access_token()

def get_access_token():
    global ACCESS_TOKEN

    if not API_KEY or not REFRESH_TOKEN:
        raise ValueError("API_KEY or REFRESH_TOKEN missing in .env")
    print(API_KEY)
    print(REFRESH_TOKEN)
    headers = {
        "x-api-key": API_KEY,
        "Authorization": f"Bearer {REFRESH_TOKEN}"
    }

    response = requests.get(f"{BASE_URL}/get_access_token", headers=headers)
    if response.status_code == 200:
        ACCESS_TOKEN = response.json().get("message", {}).get("access_token")
        if not ACCESS_TOKEN:
            raise Exception("Access token not present in response")
        return ACCESS_TOKEN
    else:
        raise Exception("Failed to get access token")

def auth_headers():
    if not ACCESS_TOKEN:
        get_access_token()
    return {
        "x-api-key": API_KEY,
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }

def get_devices():
    response = requests.get(f"{BASE_URL}/get_list_of_devices", headers=auth_headers())
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception("Failed to get devices")

def get_device_state(device_id="all"):
    response = requests.get(f"{BASE_URL}/get_device_state?device_id={device_id}", headers=auth_headers())
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception("Failed to get device state")

def send_command(device_id: str, command: dict):
    payload = {
        "device_id": device_id,
        "command": command
    }
    response = requests.post(f"{BASE_URL}/send_command", json=payload, headers=auth_headers())
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception("Failed to send command")
