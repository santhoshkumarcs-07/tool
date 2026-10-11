"""
Video Ingestion Service — URL validation, YouTube caption fetching, and Instagram direct extraction.

Directly visits YouTube and Instagram Reel links to extract captions, transcripts,
and content without requiring manual user downloads.
"""

import re
import os
import shutil
import tempfile
import urllib.parse
import logging
from typing import Dict, Any, Optional, Tuple, List
import requests

logger = logging.getLogger(__name__)

# Supported domains
YOUTUBE_DOMAINS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
INSTAGRAM_DOMAINS = ("instagram.com", "www.instagram.com")


class VideoIngestionError(Exception):
    """Raised when video ingestion or validation fails."""
    pass


def is_safe_url(url: str) -> bool:
    """Validate that the URL does not point to internal, private, or loopback IP addresses."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        # Block localhost, loopbacks, and private network ranges
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return False
        if hostname.startswith("192.168.") or hostname.startswith("10.") or hostname.startswith("172."):
            return False
        if hostname.endswith(".local") or hostname.endswith(".internal"):
            return False
        return True
    except Exception:
        return False


def identify_source_type(url: str) -> str:
    """Identify if URL is YouTube or Instagram."""
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        for d in YOUTUBE_DOMAINS:
            if hostname == d or hostname.endswith("." + d):
                return "youtube"
        for d in INSTAGRAM_DOMAINS:
            if hostname == d or hostname.endswith("." + d):
                return "instagram"
    except Exception:
        pass
    return "unsupported"


def extract_youtube_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats."""
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if "youtu.be" in hostname:
        return parsed.path.lstrip("/").split("?")[0].split("/")[0]

    if "youtube.com" in hostname:
        if parsed.path == "/watch":
            query = urllib.parse.parse_qs(parsed.query)
            return query.get("v", [None])[0]
        elif parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("/")[0].split("?")[0]
        elif parsed.path.startswith("/embed/"):
            return parsed.path.split("/embed/")[1].split("/")[0].split("?")[0]

    return None


def fetch_youtube_transcript(video_id: str) -> Tuple[str, list]:
    """
    Fetch accessible transcript/captions for a YouTube video.
    Returns (full_transcript_text, segments_with_timestamps).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'en-US', 'en-GB'])
        full_text = " ".join([seg.get("text", "") for seg in transcript_list])
        return full_text, transcript_list
    except ImportError:
        pass
    except Exception as e:
        logger_msg = str(e)
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            transcript_list_obj = YouTubeTranscriptApi.list_transcripts(video_id)
            for t in transcript_list_obj:
                data = t.fetch()
                full_text = " ".join([seg.get("text", "") for seg in data])
                return full_text, data
        except Exception:
            pass

    # Fallback: Download audio and run genuine speech-to-text using faster-whisper
    temp_dir = None
    try:
        import yt_dlp
        from faster_whisper import WhisperModel  # type: ignore
        from services.transcription_service import get_ffmpeg_path

        get_ffmpeg_path()  # ensures ffmpeg binary is in os.environ["PATH"]
        temp_dir = tempfile.mkdtemp()
        media_file = os.path.join(temp_dir, f"yt_{video_id}.mp4")

        ydl_opts = {
            'outtmpl': media_file,
            'format': 'best[height<=360]/ba+bv[height<=360]/ba/best',
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 50 * 1024 * 1024,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        if os.path.exists(media_file) and os.path.getsize(media_file) > 1000:
            logger.info(f"Running faster-whisper on YouTube media ({video_id})...")
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments_iter, _ = model.transcribe(media_file, beam_size=1)
            spoken_parts = []
            segments_list = []
            for s in segments_iter:
                txt = s.text.strip()
                if txt:
                    spoken_parts.append(txt)
                    segments_list.append({"start": s.start, "end": s.end, "text": txt})

            # Extract visible on-screen text, code, terminal commands from video frames
            visual_ctx = extract_video_visual_context(media_file, max_frames=12, interval_seconds=20.0)
            if spoken_parts:
                full_text = " ".join(spoken_parts) + (visual_ctx or "")
                return full_text, segments_list
    except Exception as e:
        logger.warning(f"YouTube Whisper audio/video transcription failed or unavailable: {e}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Fallback to yt-dlp metadata if speech could not be transcribed
    try:
        import yt_dlp
        ydl_opts = {'quiet': True, 'skip_download': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            desc = info.get("description", "")
            title = info.get("title", "")
            if desc or title:
                full_text = f"Title: {title}\n\nDescription & Notes:\n{desc}"
                return full_text, []
    except Exception as e:
        logger.debug(f"yt-dlp YouTube fallback: {e}")

    raise VideoIngestionError(
        f"Could not retrieve captions or transcript for YouTube video ({video_id}). "
        "The creator may have disabled subtitles and public descriptions."
    )


def fetch_instagram_content(url: str) -> Dict[str, Any]:
    """
    Directly visits an Instagram Reel or post link and extracts content,
    caption, description, tags, and tools demonstrated without requiring manual download.
    """
    clean_url = url.split("?")[0].rstrip("/") + "/"
    content_parts = []
    title = "Instagram Reel"
    segments: List[Dict[str, Any]] = []

    # Primary Method: Download reel video and transcribe actual spoken speech
    video_file = None
    temp_dir = None
    try:
        import yt_dlp
        from faster_whisper import WhisperModel  # type: ignore

        temp_dir = tempfile.mkdtemp()
        video_file = os.path.join(temp_dir, "reel.mp4")
        ydl_opts = {
            'outtmpl': video_file,
            'format': 'best',
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 50 * 1024 * 1024,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            if info:
                t = info.get("title") or info.get("description", "").split("\n")[0][:80]
                if t:
                    title = t
                desc = info.get("description", "").strip()
                if desc:
                    content_parts.append(f"Creator Caption & Notes:\n{desc}")
                tags = info.get("tags", [])
                if tags:
                    content_parts.append(f"Tags: {', '.join(tags)}")

        if os.path.exists(video_file) and os.path.getsize(video_file) > 1000:
            logger.info("Transcribing spoken audio from reel video...")
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments_iter, _ = model.transcribe(video_file, beam_size=1)
            spoken_parts = []
            for s in segments_iter:
                spoken_parts.append(s.text.strip())
                segments.append({"start": s.start, "end": s.end, "text": s.text.strip()})

            if spoken_parts:
                spoken_transcript = " ".join(spoken_parts)
                content_parts.insert(0, f"Spoken Video Transcript:\n{spoken_transcript}")

            # Extract visible on-screen text, code, and tools from reel frames
            visual_ctx = extract_video_visual_context(video_file, max_frames=10, interval_seconds=8.0)
            if visual_ctx:
                content_parts.append(visual_ctx)

    except Exception as e:
        logger.info(f"Direct reel video transcription skipped or fallback needed: {e}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Secondary Method: If speech could not be transcribed, scrape OpenGraph / JSON-LD metadata
    if not content_parts:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            resp = requests.get(clean_url, headers=headers, timeout=12)
            if resp.status_code == 200:
                html = resp.text

                og_title = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', html, re.DOTALL | re.IGNORECASE)
                if og_title:
                    raw_title = og_title.group(1).replace("&quot;", '"').replace("&#39;", "'").strip()
                    if raw_title and "Instagram" not in raw_title:
                        title = raw_title

                og_desc = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']', html, re.DOTALL | re.IGNORECASE)
                if not og_desc:
                    og_desc = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.DOTALL | re.IGNORECASE)
                if og_desc:
                    desc_text = og_desc.group(1).replace("&quot;", '"').replace("&#39;", "'").strip()
                    content_parts.append(f"Caption Content:\n{desc_text}")

                ld_blocks = re.findall(r'<script\s+type=["\']application/ld\+json["\']>(.*?)</script>', html, re.DOTALL)
                for block in ld_blocks:
                    try:
                        import json
                        ld_data = json.loads(block.strip())
                        if isinstance(ld_data, dict):
                            c = ld_data.get("caption") or ld_data.get("articleBody") or ld_data.get("description")
                            if c and c not in "".join(content_parts):
                                content_parts.append(f"Post Content:\n{c}")
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Direct Instagram HTML fallback: {e}")

    if content_parts:
        full_text = f"Title: {title}\n\n" + "\n\n".join(content_parts)
        return {
            "source_type": "instagram",
            "title": title,
            "transcript": full_text,
            "segments": segments,
        }

    raise VideoIngestionError(
        "Could not automatically retrieve content from this Instagram link. "
        "The reel may be private or restricted by Instagram. "
        "Try copying the reel caption text into the 'Paste Transcript' tab."
    )



def process_url(url: str) -> Dict[str, Any]:
    """
    Process a video URL (YouTube or Instagram).
    Visits the link directly and extracts captions/content without requiring manual download.
    """
    url = url.strip()
    if not is_safe_url(url):
        raise VideoIngestionError("Invalid or forbidden URL. Only public HTTP/HTTPS URLs are supported.")

    source_type = identify_source_type(url)

    if source_type == "instagram":
        return fetch_instagram_content(url)

    if source_type != "youtube":
        raise VideoIngestionError(
            "Unsupported video URL domain. Supported platforms: YouTube or Instagram Reels."
        )

    video_id = extract_youtube_video_id(url)
    if not video_id:
        raise VideoIngestionError("Could not extract a valid YouTube video ID from the provided URL.")

    full_text, segments = fetch_youtube_transcript(video_id)
    return {
        "source_type": "youtube",
        "video_id": video_id,
        "title": f"YouTube Video ({video_id})",
        "transcript": full_text,
        "segments": segments,
    }


def validate_uploaded_video(filename: str, file_size_bytes: int, max_size_mb: int = 500) -> None:
    """Validate uploaded video file extension and size."""
    allowed_exts = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
    _, ext = os.path.splitext(filename.lower())
    if ext not in allowed_exts:
        raise VideoIngestionError(
            f"Unsupported video format '{ext}'. Allowed formats: {', '.join(allowed_exts)}"
        )

    max_bytes = max_size_mb * 1024 * 1024
    if file_size_bytes > max_bytes:
        raise VideoIngestionError(
            f"File size ({file_size_bytes // (1024*1024)} MB) exceeds maximum limit of {max_size_mb} MB."
        )


def extract_video_visual_context(video_path: str, max_frames: int = 15, interval_seconds: float = 15.0) -> str:
    """
    Extract visible on-screen text, code, terminal commands, and tool names
    from video keyframes using local hardware OCR (winocr/OpenCV).
    Runs silently in the background and returns formatted context to enrich the transcript.
    """
    if not os.path.exists(video_path):
        return ""

    try:
        import cv2
        import winocr

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return ""

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration_sec = total_frames / fps if fps > 0 else 0

        if duration_sec <= 0:
            cap.release()
            return ""

        # Determine timestamps to sample (every interval_seconds, up to max_frames)
        sample_times = []
        curr = min(interval_seconds, max(1.0, duration_sec / 2))
        while curr < duration_sec and len(sample_times) < max_frames:
            sample_times.append(curr)
            curr += interval_seconds

        if not sample_times and duration_sec > 1:
            sample_times = [duration_sec / 2]

        frame_contexts = []
        seen_texts = set()

        for t in sample_times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            try:
                # Resize if frame is larger than 1280px wide to accelerate OCR
                h, w = frame.shape[:2]
                if w > 1280:
                    scale = 1280 / w
                    frame = cv2.resize(frame, (1280, int(h * scale)))

                res = winocr.recognize_cv2_sync(frame)
                raw_text = (res.get("text") or "").strip()
                if not raw_text or len(raw_text) < 4:
                    continue

                # Filter out pure noise or duplicates
                lines = [line.strip() for line in raw_text.splitlines() if len(line.strip()) >= 3]
                clean_frame_text = " | ".join(lines[:8])  # keep top relevant lines
                if clean_frame_text and clean_frame_text not in seen_texts:
                    seen_texts.add(clean_frame_text)
                    m = int(t // 60)
                    s = int(t % 60)
                    ts_str = f"{m:02d}:{s:02d}"
                    frame_contexts.append(f"[{ts_str}] On-Screen: {clean_frame_text}")
            except Exception as ocr_err:
                logger.debug(f"Frame OCR at {t}s failed: {ocr_err}")

        cap.release()

        if frame_contexts:
            return "\n\nOn-Screen Visual Context (Extracted from Video Frames):\n" + "\n".join(frame_contexts)
    except Exception as e:
        logger.debug(f"Visual context extraction skipped: {e}")

    return ""
