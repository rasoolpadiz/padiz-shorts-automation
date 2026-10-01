import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

def get_authenticated_service():
    creds = None
    token_file = r"C:\youtube_pipeline\token.pickle"
    client_secret_file = r"C:\youtube_pipeline\client_secret.json"

    if os.path.exists(token_file):
        with open(token_file, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "wb") as token:
            pickle.dump(creds, token)

    return build("youtube", "v3", credentials=creds)

if __name__ == "__main__":
    print("Starting authentication flow...")
    youtube = get_authenticated_service()
    channels_response = youtube.channels().list(mine=True, part="snippet").execute()
    channel_name = channels_response["items"][0]["snippet"]["title"]
    print(f"AUTHENTICATED_SUCCESSFULLY: Channel name is '{channel_name}'")
