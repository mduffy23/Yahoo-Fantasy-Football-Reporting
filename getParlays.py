import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json
import os

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"  # Added Drive scope
]

SERVICE_ACCOUNT_FILE = "sheet_service.json"

def get_parlays(sheet_name):
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if service_account_json:
        creds = Credentials.from_service_account_info(
            json.loads(service_account_json), scopes=SCOPES
        )
    else:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            raise RuntimeError("Set the GOOGLE_SERVICE_ACCOUNT_JSON GitHub Actions secret")
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )

    client = gspread.authorize(creds)

    # Open spreadsheet
    spreadsheet = client.open("Fantasy Parlays")

    worksheet = spreadsheet.worksheet(sheet_name)  # Replace with your tab name
    data = worksheet.get_all_records()
    return pd.DataFrame(data)
