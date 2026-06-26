import os
import json
import time
import base64
import re
import argparse
from pathlib import Path
from dotenv import load_dotenv

import dropbox
from dropbox.exceptions import ApiError
from openai import OpenAI
from openai import APIError
import ffmpeg

# --- 1. Configuration & Setup ---
load_dotenv()

DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")
DROPBOX_WATCH_FOLDER = os.getenv("DROPBOX_WATCH_FOLDER", "/Raw_Ingest")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 60))
FRAME_INTERVAL = int(os.getenv("FRAME_INTERVAL", 3)) # 1 frame every X seconds
MAX_FRAMES = int(os.getenv("MAX_FRAMES", 30)) # Maximum frames to extract
TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/ai_renamer")

# Describe the creator/context so the AI can tailor its scene descriptions.
CREATOR_CONTEXT = os.getenv("CREATOR_CONTEXT", "an independent content creator")

# Categories the AI may route clips into. Override via the CATEGORIES env var
# (comma-separated). Values should be filesystem-safe folder names.
DEFAULT_CATEGORIES = "highlights,interview,tutorial,event,lifestyle,product,behind_the_scenes,funny,other"
CATEGORIES = [c.strip() for c in os.getenv("CATEGORIES", DEFAULT_CATEGORIES).split(",") if c.strip()]

PROCESSED_DB_FILE = "processed_files.json"

# Dependency Check
if not all([DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN, OPENAI_API_KEY, OPENROUTER_API_KEY]):
    print("CRITICAL: Missing API Keys in .env file. Please check .env.example")
    # We don't exit here so the code can still be imported/tested without crashing immediately
    # but in a real run, this would be an issue.

# Initialize Clients
def get_dropbox_client():
    if not all([DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN]):
        return None
    return dropbox.Dropbox(
        app_key=DROPBOX_APP_KEY,
        app_secret=DROPBOX_APP_SECRET,
        oauth2_refresh_token=DROPBOX_REFRESH_TOKEN
    )

openai_client = None
if OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

openrouter_client = None
if OPENROUTER_API_KEY:
    openrouter_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

# --- 2. State Management ---
def load_processed_files():
    if os.path.exists(PROCESSED_DB_FILE):
        with open(PROCESSED_DB_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_processed_files(processed_set):
    with open(PROCESSED_DB_FILE, "w") as f:
        json.dump(list(processed_set), f)

# --- 3. The Extraction Pipeline ---
def setup_temp_dir():
    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)

def cleanup_temp_dir():
    for f in Path(TEMP_DIR).glob("*"):
        try:
            f.unlink()
        except OSError as e:
            print(f"Error deleting local file {f}: {e}")

def extract_media(video_path):
    """Extracts audio to mp3 and frames to jpgs."""
    print(f"Extracting media from {video_path}...")
    audio_path = os.path.join(TEMP_DIR, "audio.mp3")
    frames_pattern = os.path.join(TEMP_DIR, "frame_%04d.jpg")

    try:
        # 1. Extract Audio
        (
            ffmpeg
            .input(video_path)
            .output(audio_path, acodec='libmp3lame', q=2, loglevel="error")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print("Audio extracted successfully.")
    except ffmpeg.Error as e:
        print(f"FFmpeg Audio Error: {e.stderr.decode('utf8')}")
        audio_path = None # Audio extraction failed or missing audio track

    try:
        # 2. Extract Frames
        target_fps = 1 / FRAME_INTERVAL
        try:
            probe = ffmpeg.probe(video_path)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            duration = float(video_info['duration'])
            if duration * target_fps > MAX_FRAMES:
                print(f"Video is long ({duration}s). Capping to max {MAX_FRAMES} frames.")
                target_fps = MAX_FRAMES / duration
        except Exception as e:
            print(f"Could not probe duration: {e}. Using default intervals.")

        (
            ffmpeg
            .input(video_path)
            .filter('fps', fps=target_fps)
            .output(frames_pattern, qscale=2, loglevel="error")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print("Frames extracted successfully.")
    except ffmpeg.Error as e:
        print(f"FFmpeg Video Error: {e.stderr.decode('utf8')}")
        return audio_path, []

    # Get sorted list of extracted frames
    frames = sorted(list(Path(TEMP_DIR).glob("frame_*.jpg")))
    return audio_path, [str(f) for f in frames]

# --- 4. The AI Analysis Pipeline ---
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def transcribe_audio(audio_path):
    if not audio_path or not os.path.exists(audio_path) or not openai_client:
        return ""
    
    print("Transcribing audio via Whisper...")
    try:
        with open(audio_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                response_format="text"
            )
            return transcript
    except APIError as e:
        print(f"Whisper API Error: {e}")
        return ""

def analyze_video(transcript, frame_paths):
    if not openrouter_client:
        print("ERROR: OpenRouter Client not initialized.")
        return None

    print(f"Sending {len(frame_paths)} frames and transcript to OpenRouter ({OPENROUTER_MODEL})...")
    
    # Construct base64 image payload
    image_contents = []
    for path in frame_paths:
        base64_img = encode_image(path)
        image_contents.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_img}",
                "detail": "low" # Save tokens
            }
        })
    
    # Construct the full prompt
    system_prompt = (
        f"You are an expert media archivist for {CREATOR_CONTEXT}. "
        "You are analyzing raw footage from a recent shoot or personal event. "
        "You will be provided with a text transcript of the audio (if any), and a chronological sequence of image frames. "
        "Synthesize what you see and what you hear to describe the scene."
    )

    user_text = f"Audio Transcript: '{transcript}'\n\nPlease analyze the following chronological frames from the video. "
    
    payload_content = [{"type": "text", "text": user_text}] + image_contents

    try:
        response = openrouter_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload_content}
            ],
            response_format={ "type": "json_schema", "json_schema": {
                "name": "video_metadata",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "short_filename": {
                            "type": "string",
                            "description": "5 to 8 strictly descriptive words separated by underscores. Never use spaces. Do NOT include dates or locations. Example: Smiling_Crowd_Cheering_Stage_Lights_WideShot"
                        },
                        "detailed_description": {
                            "type": "string",
                            "description": "A single detailed paragraph (3-4 sentences) summarizing the lighting, subject actions, camera movement, and audio context."
                        },
                        "category": {
                            "type": "string",
                            "enum": CATEGORIES,
                            "description": "The category that best fits the video content."
                        }
                    },
                    "required": ["short_filename", "detailed_description", "category"],
                    "additionalProperties": False
                }
            }},
            max_tokens=500
        )
        
        # The response format guarantees JSON matching our schema
        return json.loads(response.choices[0].message.content)
    
    except APIError as e:
        print(f"GPT-4o API Error: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON response: {e}")
        return None

# --- 5. Main Execution Loop ---
def process_single_file(dbx, entry, processed_set):
    print(f"\n--- Processing: {entry.name} ---")
    setup_temp_dir()
    cleanup_temp_dir() # Ensure clean slate
    local_vid_path = os.path.join(TEMP_DIR, entry.name)

    try:
        # 1. Download
        print(f"Downloading from Dropbox...")
        dbx.files_download_to_file(local_vid_path, entry.path_display)
        
        # 2. Extract Media
        audio_path, frame_paths = extract_media(local_vid_path)
        
        if not frame_paths:
            print("Failed to extract frames. Skipping.")
            return False

        # 3. Analyze Audio
        transcript = transcribe_audio(audio_path)
        
        # 4. Analyze Vision
        metadata = analyze_video(transcript, frame_paths)
        if not metadata:
            print("AI Analysis failed. Skipping.")
            return False

        # 5. Rename & Upload Context
        creation_date = entry.client_modified.strftime("%Y-%m-%d")
        
        # Clean the short_tags just in case the AI added illegal filename characters
        safe_tags = re.sub(r'[^A-Za-z0-9_]', '', metadata['short_filename'])
        new_basename = f"{creation_date}_{safe_tags}"
        
        # Get original extension (e.g. .MOV)
        _, ext = os.path.splitext(entry.name)
        new_filename = f"{new_basename}{ext}"
        new_txt_filename = f"{new_basename}.txt"
        
        # Use target folder logic with Category Routing
        original_folder_path = os.path.dirname(entry.path_display)
        if original_folder_path == "/":
            original_folder_path = ""
            
        category = metadata.get('category', 'other')
        # Sanitize the category into a filesystem-safe folder name.
        safe_category = re.sub(r'[^A-Za-z0-9_\-]', '', category) or "other"
        
        target_folder_path = f"{original_folder_path}/{safe_category}"
        target_txt_folder_path = f"{original_folder_path}/_Text_Descriptions/{safe_category}"
        
        # Ensure the category folder exists in Dropbox
        try:
            dbx.files_get_metadata(target_folder_path)
        except ApiError as e:
            if e.error.is_path() and e.error.get_path().is_not_found():
                print(f"Creating new category folder: {target_folder_path}")
                try:
                    dbx.files_create_folder_v2(target_folder_path)
                except ApiError as e_create:
                    pass
        
        # Ensure the text descriptions folder exists in Dropbox
        try:
            dbx.files_get_metadata(target_txt_folder_path)
        except ApiError as e:
            if e.error.is_path() and e.error.get_path().is_not_found():
                print(f"Creating new text description folder: {target_txt_folder_path}")
                try:
                    dbx.files_create_folder_v2(target_txt_folder_path)
                except ApiError as e_create:
                    pass
            
        new_filepath = f"{target_folder_path}/{new_filename}"
        new_txt_filepath = f"{target_txt_folder_path}/{new_txt_filename}"

        print(f"Renaming and routing to: {new_filepath}")
        
        # Check if the target file already exists to avoid conflict errors
        try:
            dbx.files_get_metadata(new_filepath)
            # If it exists, append a timestamp to make it unique
            new_basename = f"{new_basename}_{int(time.time())}"
            new_filepath = f"{target_folder_path}/{new_basename}{ext}"
            new_txt_filepath = f"{target_folder_path}/{new_basename}.txt"
            print(f"File existed, renamed to: {new_basename}{ext}")
        except ApiError:
            pass # Does not exist, safe to proceed

        # Perform the rename (move)
        dbx.files_move_v2(entry.path_display, new_filepath)
        print("Rename successful in Dropbox.")

        # Upload the sidecar text
        print("Uploading sidecar description...")
        txt_content = metadata['detailed_description'].encode('utf-8')
        dbx.files_upload(txt_content, new_txt_filepath)

        # 6. Mark Success
        processed_set.add(entry.id)
        save_processed_files(processed_set)
        print("Processing fully complete.")
        return True

    except ApiError as e:
        print(f"Dropbox API Error during processing: {e}")
        return False
    except Exception as e:
        print(f"Unexpected Error: {e}")
        return False
    finally:
        cleanup_temp_dir()

def poll_dropbox():
    dbx = get_dropbox_client()
    if not dbx:
        print("Dropbox client not initialized. Waiting for API keys in .env")
        return

    processed_set = load_processed_files()
    print(f"Started polling Dropbox folder: {DROPBOX_WATCH_FOLDER}")
    
    cursor = None
    
    while True:
        try:
            if cursor:
                result = dbx.files_list_folder_continue(cursor)
            else:
                result = dbx.files_list_folder(path=DROPBOX_WATCH_FOLDER)
            
            for entry in result.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    # Check if it's a target file
                    name_lower = entry.name.lower()
                    if name_lower.endswith(".mov") or name_lower.endswith(".mp4"):
                        # If the file hasn't been processed yet, its ID won't be in the DB
                        # But as a fallback, also check if it ALREADY matches our "YYYY-MM-DD_" naming scheme
                        if not re.match(r'^\d{4}-\d{2}-\d{2}_', entry.name):
                            if entry.id not in processed_set:
                                process_single_file(dbx, entry, processed_set)
            
            # If `has_more` is true, we immediately call `continue` with the new cursor.
            # Otherwise, we sleep and wait for changes.
            if result.has_more:
                cursor = result.cursor
                continue
                
            cursor = result.cursor
            print(f"Sleeping for {POLL_INTERVAL} seconds...")
            time.sleep(POLL_INTERVAL)
                
        except ApiError as e:
            print(f"Dropbox API Error during polling: {e}")
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"Unexpected fatal error: {e}")
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Clip Renamer - Dropbox video auto-renamer")
    parser.add_argument("--test", action="store_true", help="Run a dry-run test without Dropbox")
    args = parser.parse_args()

    if args.test:
        print("Test mode currently requires manual DBX configuration.")
        # Future enhancement: local test routine targeting a local folder
    else:
        poll_dropbox()
