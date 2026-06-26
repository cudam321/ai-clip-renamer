# AI Clip Renamer

An intelligent, zero-touch folder automation tool that automatically tags, renames, and
categorizes raw video clips uploaded to Dropbox.

It polls a target Dropbox folder, downloads raw `.mov` or `.mp4` clips, extracts the audio and
keyframes locally, and uses OpenAI Whisper (audio transcription) and an OpenRouter vision model
(keyframe analysis) to build a detailed metadata profile of each scene. It then routes the clip
into a category subfolder, renames it to `YYYY-MM-DD_Descriptive.ext`, and writes a searchable
`.txt` sidecar description into a structured `_Text_Descriptions` folder — keeping your Dropbox
organized and searchable without cluttering the delivery folders.

## System Architecture

```text
 Dropbox Watch Folder (/Raw_Ingest)
  └── [IMG_XXXX.mov]
       │
       ▼
 Local Downloader (Python)
  └── Downloads to /tmp/ai_renamer/
       │
       ├─► FFmpeg extracts Audio ──────► [audio.mp3] ─────────► OpenAI Whisper API ─────┐
       │                                                                                │
       └─► FFmpeg extracts Frames ────► [frame_01.jpg ...] ──► OpenRouter Vision API ──┼──► AI Context
                                                                                        │    Synthesis
                                                                                        │
                       ┌────────────────────────────────────────────────────────────────┘
                       │
                       ├─► Category Routing ──► Creates /<category>/ folder
                       │
                       ├─► 5-8 Word Title   ──► Renames to YYYY-MM-DD_Wide_Shot_Stage.mov ─► Uploads to /<category>/
                       │
                       └─► Scene Narrative  ──► Saves to YYYY-MM-DD_Wide_Shot_Stage.txt ───► Uploads to /_Text_Descriptions/
```

## Features

* **Audio + Visual Context Mapping:** Uses FFmpeg to extract an audio track (for OpenAI Whisper
  transcription) and video keyframes (for an OpenRouter multimodal vision model) to build a
  unified understanding of each clip's lighting, subjects, and audio context.
* **Automated Naming & Routing:** Renames non-descriptive files (e.g. `IMG_4821.mov`) to a
  strictly formatted 5-8 word description prefixed by the original creation date
  (e.g. `2024-05-12_Wide_Shot_Stage_Lights_Crowd.mov`).
* **Configurable Categorization:** Maps visual context to a configurable set of category buckets
  (see `CATEGORIES` in `.env.example`) and automatically creates the routing folders in Dropbox
  if they do not yet exist.
* **Text Sidecar Injection:** Writes a 3-4 sentence narrative of the scene into a matching `.txt`
  file, routed to a dedicated `_Text_Descriptions` folder for searchability.
* **Configurable Context:** The `CREATOR_CONTEXT` env var lets you describe who/what the footage
  is about so the AI tailors its descriptions.
* **Loop Safety:** Tracks processed jobs locally in `processed_files.json` (created at runtime)
  and uses a regex filename check to skip files that are already cleanly formatted.

## Prerequisites

1. **Python 3.10+**
2. **FFmpeg** installed on the host system.
   * macOS: `brew install ffmpeg`
   * Debian/Ubuntu: `sudo apt install ffmpeg`
3. **API keys:**
   * **Dropbox:** A registered Dropbox app with `files.metadata.read`, `files.content.read`,
     and `files.content.write` permissions.
   * **OpenAI:** For Whisper audio transcription.
   * **OpenRouter:** For vision/text synthesis.

## Installation

1. Clone or download this repository.
2. Create and activate a virtual environment, then install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## Configuration

1. Copy the example environment template:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in your **Dropbox App Key**, **Dropbox App Secret**, **OpenAI API Key**,
   and **OpenRouter API Key**. Set `DROPBOX_WATCH_FOLDER` to the path where raw uploads land
   (e.g. `/Raw_Ingest`). Optionally set `CREATOR_CONTEXT` and `CATEGORIES`.
3. **Generate a Dropbox refresh token.** This tool runs as a long-lived daemon, so it needs an
   offline refresh token. Run the helper script and follow the prompts:
   ```bash
   python setup_dropbox.py
   ```
   It prints an authorization URL, you click **Allow** in the browser, paste the returned access
   code, and the script exchanges it for a refresh token and writes it back into `.env`.

You can verify your Dropbox access and discover folder paths with:
```bash
python debug_dropbox.py
```

## Running

Run the watcher in the foreground (best for testing):
```bash
python main.py
```

It polls on an infinite loop controlled by `POLL_INTERVAL` (default: 60 seconds). Press
`CTRL + C` to stop.

### Optional: run as a background service (macOS launchd)

A sample launchd job is included as `com.example.airenamer.plist`.

1. Edit the plist and replace every `/path/to/ai-clip-renamer/...` placeholder with the real
   absolute paths to your venv Python binary, `main.py`, and the project directory.
2. Copy it into your LaunchAgents directory and load it:
   ```bash
   cp com.example.airenamer.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.example.airenamer.plist
   ```
   Logs are written to `/tmp/ai_renamer.log` and `/tmp/ai_renamer_error.log`.
3. To stop the service:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.example.airenamer.plist
   ```

## How it stores state

The tool uses the local `/tmp/` directory (configurable via `TEMP_DIR`) to stage high-fidelity
files during extraction. These are wiped at the end of every analysis loop, regardless of
success or API failure. Processed-file IDs are tracked in `processed_files.json`, which is
created automatically on first run (ship-safe `processed_files.json.example` is included).

## License

MIT — see [LICENSE](LICENSE).
