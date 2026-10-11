# AI Tool Discovery — Public Deployment & Android APK Guide

This document provides step-by-step instructions for deploying the **AI Tool Discovery** backend to verified **₹0 free hosting** and building the companion **Android APK**.

---

## 1. System Architecture

```
[Android APK / Mobile Browser]
           │
           │  HTTPS (TLS 1.3)
           ▼
[Gunicorn WSGI / Reverse Proxy]
           │
           ├──► [Flask Backend (app.py)]
           │           │
           │           ├──► [Session Security & User Isolation]
           │           │
           │           └──► [ThreadPool Background Executor]
           │                       │
           │                       ├──► [FFmpeg Audio Extraction (16kHz WAV)]
           │                       ├──► [Faster-Whisper STT (CPU int8 tiny)]
           │                       ├──► [Tesseract OCR Frame Reader]
           │                       └──► [OpenRouter Free LLM Gateway]
           │
           └──► [Persistent Storage (data/)]
                       ├── tool_discovery.db (SQLite WAL Mode)
                       ├── transcripts/ (*.json)
                       └── uploads/ (UUID_filename.mp4)
```

---

## 2. Free Hosting Options (Verified ₹0 Budget)

| Provider | Specs | Persistence | Processing Capacity | Setup Simplicity |
| :--- | :--- | :--- | :--- | :--- |
| **Option A: Hugging Face Spaces (Docker)** *(Easiest & Instant)* | 2 vCPU, 16 GB RAM, 50 GB disk | Available via Spaces storage / Git sync | Runs Faster-Whisper, FFmpeg, and Tesseract effortlessly without OOM | ⭐⭐⭐⭐⭐ Zero credit card required, instant public HTTPS URL |
| **Option B: Oracle Cloud Always Free VM** *(Most Robust)* | 4 Arm Ampere cores, 24 GB RAM, 200 GB block storage | Full native persistent disk | Outstanding (full Linux root, unlimited runtime) | ⭐⭐⭐⭐ Requires one-time identity card verification (charges ₹0) |
| **Option C: Koyeb / Render Free** | 0.1 CPU, 512 MB RAM | Ephemeral (wiped on restart) | ⚠️ High risk of OOM kills on video transcription; sleeps when idle | ⭐⭐ Not recommended for heavy video processing |

---

## 3. Option A Deployment Walkthrough: Hugging Face Spaces (Instant & Free)

Hugging Face Spaces provides a **free container** with **2 vCPUs and 16 GB RAM** and gives you a free public HTTPS domain (e.g. `https://<username>-tool-discovery.hf.space`).

### Step 1: Create a New Space
1. Go to [huggingface.co/new-space](https://huggingface.co/new-space).
2. Space name: `tool-discovery`.
3. License: `mit` or `apache-2.0`.
4. Space SDK: Select **Docker** (Blank).
5. Hardware: **CPU Basic • 2 vCPU • 16GB RAM** (Free).
6. Click **Create Space**.

### Step 2: Set Environment Secrets
In your Space settings (**Settings** → **Variables and secrets** → **New secret**):
- `OPENROUTER_API_KEY`: Your OpenRouter API key (`sk-or-v1-...`).
- `FLASK_SECRET_KEY`: A random secret string (e.g. `openssl rand -hex 32`).
- `ENABLE_HTTPS`: `true`.

### Step 3: Push Code to Space
Clone your Space repository and push this codebase:
```bash
git remote add space https://huggingface.co/spaces/<your-username>/tool-discovery
git push space feature/public-deployment-and-apk:main
```
The Space will automatically build the `Dockerfile`, install system FFmpeg and Tesseract, launch Gunicorn WSGI, and provide your live public HTTPS URL!

---

## 4. Option B Deployment Walkthrough: Oracle Cloud Always Free Linux VM

If you have an Oracle Cloud Always Free account:

### Step 1: Launch Ubuntu VM
- Image: **Ubuntu 22.04 LTS** (or 24.04 LTS).
- Shape: **VM.Standard.A1.Flex** (4 OCPUs, 24 GB RAM) or **VM.Standard.E2.1.Micro** (1 OCPU, 1 GB RAM).
- Open Ports: In your VCN Ingress Rules, allow TCP `80`, `443`, and `5000`.

### Step 2: Install Docker & Git on the VM
```bash
sudo apt update && sudo apt install -y docker.io docker-compose git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

### Step 3: Clone & Run via Docker Compose
```bash
git clone <your-repo-url> tool-discovery
cd tool-discovery

# Copy and configure your environment
cp .env.example .env
nano .env  # Add your OPENROUTER_API_KEY

# Start the background container
docker-compose up -d --build
```

### Step 4: Add Free HTTPS with Caddy
Install Caddy for automatic Let's Encrypt SSL:
```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# Configure /etc/caddy/Caddyfile:
# your-domain.com {
#     reverse_proxy localhost:5000
# }
sudo systemctl restart caddy
```

---

## 5. Android APK Build & Configuration

The companion Android application is located in the `android/` directory.

### Step 1: Configure Your Hosted Backend URL
Open `android/app/src/main/res/values/strings.xml` and replace the placeholder URL with your public hosted HTTPS URL:
```xml
<string name="backend_base_url">https://your-app-host.com</string>
```

### Step 2: Build the APK

#### Method A: Using Android Studio (Recommended)
1. Open **Android Studio**.
2. Select **Open** and choose the `android/` folder.
3. Wait for Gradle to sync dependencies.
4. Select **Build** → **Build Bundle(s) / APK(s)** → **Build APK(s)**.
5. Once complete, click **locate** to find `app-debug.apk` in:
   `android/app/build/outputs/apk/debug/app-debug.apk`

#### Method B: Using Gradle Command Line (If JDK is installed)
On Windows:
```cmd
cd android
gradlew.bat assembleDebug
```
On Linux / macOS:
```bash
cd android
chmod +x gradlew
./gradlew assembleDebug
```
The output APK will be generated at:
`android/app/build/outputs/apk/debug/app-debug.apk`

### Step 3: Generating a Signed Release APK for Distribution
To share with family, friends, or public users without debug warnings:
1. In Android Studio: **Build** → **Generate Signed Bundle / APK**.
2. Select **APK** → Next.
3. Create a new Keystore (`release.keystore`), set alias and password.
4. Select **release** build type and check **V1 (Jar Signature)** & **V2 (Full APK Signature)**.
5. Click **Finish**. Your signed release APK is ready to distribute!

---

## 6. Database Backup & Restore

### Backup
SQLite database and metadata files can be backed up while the server is running (WAL mode ensures non-blocking hot backups):
```bash
# Hot backup using SQLite backup command
sqlite3 data/tool_discovery.db ".backup data/tool_discovery_backup.db"

# Archive database and transcripts
tar -czvf backup_$(date +%Y%m%d).tar.gz data/tool_discovery_backup.db data/transcripts/
```

### Restore
```bash
tar -xzvf backup_YYYYMMDD.tar.gz
mv data/tool_discovery_backup.db data/tool_discovery.db
```

---

## 7. Security & Privacy Summary
- **Zero API Key Leakage**: The OpenRouter API key resides strictly in server environment variables. It is never exposed in the client HTML/JS or embedded in the Android APK.
- **Path Traversal Protection**: Media file requests are strictly sanitized (`os.path.basename`) against directory traversal.
- **Isolated User Sessions**: Each client receives an isolated session UUID via signed HTTP-only cookies and `X-User-ID` headers.
- **Safe Subprocess Invocation**: Audio extraction uses strict list-based arguments with parameterized inputs (no shell execution).
