"""
Transcription Service — Audio extraction via FFmpeg and replaceable STT engine.

Provides modular speech-to-text processing for uploaded video files.
Supports timestamp extraction and chunking for long transcripts.
Includes graceful error messaging if FFmpeg or local STT models are not yet installed.
"""

import os
import shutil
import subprocess
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when audio extraction or transcription fails."""
    pass


def get_ffmpeg_path() -> Optional[str]:
    """Find ffmpeg executable in PATH or from imageio-ffmpeg bundled binaries."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        bin_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        ffmpeg_exe = os.path.join(bin_dir, "ffmpeg.exe")
        if os.path.exists(ffmpeg_exe):
            if bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            return ffmpeg_exe
        alt_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(alt_exe):
            return alt_exe
    except Exception:
        pass
    return None


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg executable is available in PATH or imageio-ffmpeg."""
    return get_ffmpeg_path() is not None


def extract_audio(video_path: str, output_audio_path: str) -> str:
    """
    Extract audio from video file using FFmpeg into a 16kHz mono WAV file.
    """
    ffmpeg_exe = get_ffmpeg_path()
    if not ffmpeg_exe:
        raise TranscriptionError(
            "FFmpeg is not installed or not found in system PATH. "
            "Please install FFmpeg to enable audio extraction from uploaded videos."
        )

    if not os.path.exists(video_path):
        raise TranscriptionError(f"Video file not found: {video_path}")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)

    cmd = [
        ffmpeg_exe,
        "-y",               # Overwrite output
        "-i", video_path,   # Input video
        "-vn",              # Disable video recording
        "-acodec", "pcm_s16le", # 16-bit PCM WAV
        "-ar", "16000",     # 16kHz sample rate
        "-ac", "1",         # Mono channel
        output_audio_path
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return output_audio_path
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode(errors="ignore") if e.stderr else str(e)
        raise TranscriptionError(f"FFmpeg audio extraction failed: {stderr_msg[:300]}")
    except Exception as e:
        raise TranscriptionError(f"Failed to run FFmpeg: {str(e)}")


def transcribe_audio_file(audio_path: str, engine: str = "whisper") -> Dict[str, Any]:
    """
    Transcribe audio file using a local speech-to-text engine (e.g. whisper or faster-whisper).
    Returns dict with full_text and segments list with timestamps.
    """
    if not os.path.exists(audio_path):
        raise TranscriptionError(f"Audio file not found: {audio_path}")

    # Try faster-whisper first if installed
    try:
        from faster_whisper import WhisperModel  # type: ignore
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, info = model.transcribe(audio_path, beam_size=1)
        seg_list = []
        full_text_parts = []
        for s in segments:
            seg_list.append({
                "start": s.start,
                "end": s.end,
                "text": s.text.strip()
            })
            full_text_parts.append(s.text.strip())
        return {
            "engine": "faster-whisper",
            "full_text": " ".join(full_text_parts),
            "segments": seg_list
        }
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"faster-whisper failed: {e}")

    # Try openai-whisper if installed
    try:
        # pyrefly: ignore [missing-import]
        import whisper
        model = whisper.load_model("tiny")
        result = model.transcribe(audio_path)
        seg_list = []
        for s in result.get("segments", []):
            seg_list.append({
                "start": s.get("start", 0),
                "end": s.get("end", 0),
                "text": s.get("text", "").strip()
            })
        return {
            "engine": "openai-whisper",
            "full_text": result.get("text", "").strip(),
            "segments": seg_list
        }
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"openai-whisper failed: {e}")

    raise TranscriptionError(
        "No local speech-to-text engine (faster-whisper or whisper) is installed in the current Python environment. "
        "Please install faster-whisper or use YouTube URLs with captions / Paste Transcript mode."
    )


def chunk_transcript(segments: List[Dict[str, Any]], max_chars: int = 12000) -> List[str]:
    """
    Split long transcripts into logical chunks preserving timestamps.
    """
    chunks = []
    current_chunk = []
    current_len = 0

    for seg in segments:
        text = seg.get("text", "")
        start = seg.get("start", "")
        line = f"[{start}s] {text}" if start != "" else text
        
        if current_len + len(line) > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = len(line)
        else:
            current_chunk.append(line)
            current_len += len(line)

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks or [""]
