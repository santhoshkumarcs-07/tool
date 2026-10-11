# Personal AI Tool Discovery and Installation Assistant

A private, responsive web application for discovering AI tools, developer utilities, MCP servers, coding agents, and automation utilities from YouTube videos, Instagram Reels, and local video uploads—with one-click integration into **Claude Code** and **VS Code**.

---

## Key Features

1. **Video Ingestion & Caption Processing**:
   - **YouTube**: Retrieves accessible public captions and transcripts.
   - **Instagram Reels**: Detects Instagram URLs and provides clear explanations of platform access/login restrictions, guiding users to upload the video file directly.
   - **Local Video Uploads**: Validates file size ($\le 500$ MB) and video duration ($\le 20$ minutes).
2. **Audio Extraction & Transcription**:
   - Audio extraction powered by FFmpeg (16kHz mono WAV).
   - Modular, replaceable speech-to-text interface with timestamp preservation.
3. **OpenRouter Exclusive Free Model Gateway**:
   - Connects exclusively to OpenRouter (`https://openrouter.ai/api/v1`).
   - Automatically filters available models using OpenRouter pricing metadata for free tiers (`$0.00/0.00`).
   - Cycles through fallback free models on rate limits (HTTP 429).
   - **Guaranteed zero unintended cost**: Strictly prohibits silent switching to paid models.
   - Keeps your API key safe on the local backend—never exposed to browser JavaScript.
4. **Structured Tool Extraction & Evidence Preservation**:
   - Pydantic validation for extracted tool records.
   - Preserves timestamps and transcript quotes supporting each tool claim.
   - Verifies official repositories and documentation URLs against trusted developer ecosystems.
5. **Personal Library**:
   - Search, category filter chips (MCP Server, Coding Agent, AI Tool, Dev Tool, Library, Automation, App).
   - Save, remove, and manage personal notes in local SQLite.
6. **One-Click AI Application Integration & Local Companion**:
   - **Install in AI App** action on every tool card.
   - Structured installation plans tailored for **Claude Code** and **VS Code**.
   - Identifies integration type (`mcp-server`, `extension`, `skill`, `package`, `manual`).
   - Previews prerequisites, required permissions, commands, configuration diffs, and security risks.
   - **Local Companion Agent**: Safe, local execution of explicitly approved actions (e.g. configuring `~/.claude.json` or `.vscode/settings.json`, running `code --install-extension`).
   - Strict security bounds: no arbitrary shell strings; input sanitization; requires explicit user approval confirmation.

---

## Quickstart

### 1. Requirements
- Python 3.10+
- (Optional) FFmpeg in your system PATH for local video file audio extraction.

### 2. Setup Environment
```bash
# Clone or navigate to the project directory
cd "tool-discovery"

# Copy environment template
cp .env.example .env

# Edit .env and insert your OpenRouter API key:
# OPENROUTER_API_KEY=your_actual_key_here
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run Automated Test Suite
```bash
python -m pytest tests/ -v
```
*(All 75 unit and integration tests covering OpenRouter gateway, Video Ingestion, Verification, Adapters, Companion, and Database will run).*

### 5. Launch the Web Application
```bash
python app.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

---

## Architecture Overview

```
tool-discovery/
├── app.py                     # Flask application factory & API routes
├── gunicorn.conf.py           # Production WSGI server configuration
├── Dockerfile                 # Multi-stage container with FFmpeg & Tesseract
├── docker-compose.yml         # Container deployment with persistent volume
├── DEPLOYMENT.md              # Free hosting walkthrough (₹0 budget) & APK build guide
├── requirements.txt           # Python dependencies
├── .env.example               # Configuration template
├── index.html                 # Responsive single-page application & Studio
├── style.css                  # Dark developer dashboard design
├── script.js                  # Frontend controllers, media recorder, & live polling
├── android/                   # Native Android WebView APK Project (Kotlin)
│   ├── app/src/main/
│   │   ├── AndroidManifest.xml
│   │   ├── java/com/tooldiscovery/app/MainActivity.kt
│   │   └── res/ (layouts, themes, colors, icons)
│   ├── build.gradle.kts
│   └── gradlew.bat
├── services/
│   ├── llm_provider.py        # OpenRouter exclusive free-model gateway
│   ├── extraction_service.py  # Pydantic extraction & validation
│   ├── video_service.py       # URL validation, caption fetcher, & cross-platform OCR
│   ├── transcription_service.py # Audio extraction & Faster-Whisper STT
│   ├── verification_service.py # Official URL & repository verification
│   ├── configuration_service.py # Claude Code & VS Code install plan adapters
│   └── companion_service.py   # Local companion execution agent
├── database/
│   ├── db.py                  # Parameterized SQLite query helpers with WAL mode
│   └── schema.sql             # Relational schema (videos, tools, library, jobs)
├── tests/
│   ├── test_phase1.py         # Base routes & database tests
│   ├── test_phase2.py         # Mocked LLM extraction & validation tests
│   └── test_new_features.py   # Free models, OCR, Companion, Security, & Async tests
└── data/                      # Local SQLite database & uploaded media (git-ignored)
```

---

## Public Deployment & Android APK

For detailed step-by-step instructions on deploying the application to verified **₹0 free hosting** (Hugging Face Spaces Docker container or Oracle Cloud Always Free VM) and building the companion Android APK, see [DEPLOYMENT.md](file:///e:/content/retriever/tool-discovery/DEPLOYMENT.md).

### Quick Docker Launch
```bash
docker-compose up -d --build
```

### Quick Android Build
```bash
cd android
./gradlew assembleDebug  # Generates android/app/build/outputs/apk/debug/app-debug.apk
```

---

## Security Model

- **Session Isolation**: Each user gets an isolated session space; personal library entries and analysis runs are scoped per user.
- **SSRF Prevention**: All fetched URLs are validated against private, loopback, and internal CIDR addresses.
- **Path Traversal Protection**: Media streaming routes strictly sanitize filenames (`os.path.basename`).
- **Security Headers**: Standard production headers enabled (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection`).
- **Untrusted Media Processing**: Videos, transcripts, and LLM outputs are treated as untrusted input. No arbitrary command execution is permitted.
- **Companion Safeguards**: Automated actions run only with explicit modal approval, using whitelisted parameter formats and safe process invocations.
