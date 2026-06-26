import os
import dropbox
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("DROPBOX_APP_KEY")
APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")

if not all([APP_KEY, APP_SECRET, REFRESH_TOKEN]):
    print("Missing auth keys in .env")
    exit(1)

dbx = dropbox.Dropbox(
    app_key=APP_KEY,
    app_secret=APP_SECRET,
    oauth2_refresh_token=REFRESH_TOKEN
)

print("\n--- Checking Dropbox Root Access ---")
try:
    # An empty string "" refers to the root folder the app has access to.
    res = dbx.files_list_folder(path="")
    print("Files/Folders found at the root of your App's access:")
    for entry in res.entries:
        print(f"- {entry.name} (Path Display: {entry.path_display})")
    print(f"\nTotal entries found: {len(res.entries)}")
    print("If this is empty, the app folder is completely empty.")
    print("If it lists folders, try using their 'Path Display' as your DROPBOX_WATCH_FOLDER in .env")
except Exception as e:
    print(f"Error accessing root: {e}")
