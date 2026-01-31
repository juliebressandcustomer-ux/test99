from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import subprocess, requests, uuid, os, textwrap, logging

# ===============================
# LOGGING (Railway)
# ===============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()

# ===============================
# DEBUG ENDPOINTS
# ===============================
@app.get("/debug/fonts")
def debug_fonts():
    """Check which fonts are actually available on the system"""
    font_status = {}
    
    for font_name, font_path in SYSTEM_FONTS.items():
        exists = os.path.exists(font_path)
        font_status[font_name] = {
            "path": font_path,
            "exists": exists,
            "size": os.path.getsize(font_path) if exists else None
        }
    
    return {
        "system_fonts": font_status,
        "default_font": DEFAULT_FONT,
        "env": {
            "LC_ALL": os.environ.get("LC_ALL"),
            "LANG": os.environ.get("LANG")
        }
    }

@app.get("/")
def root():
    return {
        "status": "running",
        "version": "2.0.0",
        "features": [
            "Text animations (fade, slide, zoom, typewriter)",
            "Multiple video concatenation with transitions",
            "Background music mixing",
            "Auto line breaks for long text",
            "French accent support"
        ],
        "endpoints": {
            "convert": "POST /convert",
            "download": "GET /download/{uid}",
            "debug_fonts": "GET /debug/fonts",
            "debug_ffmpeg": "GET /debug/ffmpeg"
        }
    }

@app.get("/debug/ffmpeg")
def debug_ffmpeg():
    """Check FFmpeg capabilities"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True,
            text=True,
            timeout=5
        )
        has_subtitles = "subtitles" in result.stdout
        has_drawtext = "drawtext" in result.stdout
        has_concat = "concat" in result.stdout
        
        return {
            "ffmpeg_available": True,
            "filters": {
                "subtitles": has_subtitles,
                "drawtext": has_drawtext,
                "concat": has_concat
            },
            "version_info": result.stderr.split('\n')[0] if result.stderr else "Unknown"
        }
    except Exception as e:
        return {"error": str(e)}

TMP_DIR = "/tmp"
SYSTEM_FONTS = {
    "Arial-Bold.ttf": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "Arial.ttf": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "Impact.ttf": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "Montserrat-Bold.ttf": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
}
DEFAULT_FONT = "Arial-Bold.ttf"

# ===============================
# INPUT MODEL
# ===============================
class ConvertRequest(BaseModel):
    drive_urls: List[str]                   # Multiple video URLs
    text: str
    format: str = "1:1"                     # 1:1 | 4:5 | 9:16
    font: str = DEFAULT_FONT
    font_size: int = 64
    text_position: str = "top"              # top | center | bottom
    text_offset: int = 0                    # vertical offset (px)
    
    # NEW PARAMETERS
    text_animation: str = "none"            # none | fade | slide_up | slide_down | zoom | typewriter
    animation_duration: float = 1.0         # Duration of animation in seconds
    
    video_transition: str = "none"          # none | fade | dissolve | wipe
    transition_duration: float = 0.5        # Duration between videos
    
    music_url: Optional[str] = None         # Background music MP3 URL
    music_volume: float = 0.3               # 0.0 to 1.0
    
    max_chars_per_line: int = 20            # Auto line break

# ===============================
# SMART WRAP WITH AUTO LINE BREAKS
# ===============================
def smart_wrap(text: str, font_size: int, max_chars: int) -> List[str]:
    """Smart text wrapping with automatic line breaks"""
    text = text.upper()
    
    # Adjust max chars based on font size
    if font_size <= 56:
        width = min(max_chars, 24)
    elif font_size <= 64:
        width = min(max_chars, 20)
    elif font_size <= 72:
        width = min(max_chars, 16)
    else:
        width = min(max_chars, 12)
    
    lines = textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False)
    
    # Limit to 3 lines maximum
    if len(lines) > 3:
        lines = [lines[0], lines[1], " ".join(lines[2:])]
    
    return lines

# ===============================
# ANIMATION BUILDER
# ===============================
def build_text_animation(line: str, font_path: str, font_size: int, 
                        y_pos: int, animation: str, duration: float, 
                        video_duration: float) -> str:
    """Build FFmpeg drawtext filter with animation"""
    
    # Escape special characters
    escaped_line = line.replace("'", "'\\\\\\''").replace(":", "\\:")
    
    base = (
        f"drawtext=fontfile='{font_path}':"
        f"text='{escaped_line}':"
        f"fontsize={font_size}:"
        f"fontcolor=white:"
        f"borderw=3:"
        f"bordercolor=black:"
        f"x=(w-text_w)/2"
    )
    
    if animation == "fade":
        # Fade in animation
        return (
            f"{base}:"
            f"y={y_pos}:"
            f"enable='between(t,0,{video_duration})':"
            f"alpha='if(lt(t,{duration}),t/{duration},1)'"
        )
    
    elif animation == "slide_up":
        # Slide from bottom
        start_y = y_pos + 200
        return (
            f"{base}:"
            f"y='if(lt(t,{duration}),{start_y}-(({start_y}-{y_pos})*t/{duration}),{y_pos})'"
        )
    
    elif animation == "slide_down":
        # Slide from top
        start_y = y_pos - 200
        return (
            f"{base}:"
            f"y='if(lt(t,{duration}),{start_y}+(({y_pos}-{start_y})*t/{duration}),{y_pos})'"
        )
    
    elif animation == "zoom":
        # Zoom in effect
        return (
            f"{base}:"
            f"y={y_pos}:"
            f"fontsize='if(lt(t,{duration}),{font_size}*0.5+({font_size}*0.5*t/{duration}),{font_size})'"
        )
    
    elif animation == "typewriter":
        # Typewriter effect (reveal characters progressively)
        num_chars = len(line)
        chars_per_sec = num_chars / duration
        return (
            f"{base}:"
            f"y={y_pos}:"
            f"text='{escaped_line}':"
            f"start_number=0:"
            f"textfile="
        )
        # Note: True typewriter needs character-by-character rendering
        # Simplified version: use fade with expansion parameter
        return (
            f"{base}:"
            f"y={y_pos}:"
            f"expansion=none:"
            f"alpha='if(lt(t,{duration}),t/{duration},1)'"
        )
    
    else:  # none
        return f"{base}:y={y_pos}"

# ===============================
# VIDEO CONCATENATION
# ===============================
def concatenate_videos(video_paths: List[str], transition: str, 
                      transition_duration: float, output_path: str,
                      target_width: int, target_height: int) -> float:
    """Concatenate multiple videos with transitions"""
    
    if len(video_paths) == 1:
        # Single video, just scale it
        cmd = [
            "ffmpeg", "-y", "-i", video_paths[0],
            "-vf", f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, check=True)
        
        # Get duration
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            output_path
        ]
        duration_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        return float(duration_result.stdout.strip())
    
    # Multiple videos - need to concat with transitions
    if transition == "none":
        # Simple concatenation
        concat_file = output_path.replace(".mp4", "_concat.txt")
        with open(concat_file, "w") as f:
            for vp in video_paths:
                f.write(f"file '{vp}'\n")
        
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-vf", f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "fast",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
    
    elif transition in ["fade", "dissolve"]:
        # Crossfade transition using xfade filter
        filter_parts = []
        inputs = []
        
        for i, vp in enumerate(video_paths):
            inputs.extend(["-i", vp])
        
        # Scale all inputs first
        for i in range(len(video_paths)):
            filter_parts.append(
                f"[{i}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2[v{i}]"
            )
        
        # Build xfade chain
        current = "[v0]"
        for i in range(1, len(video_paths)):
            if i == 1:
                filter_parts.append(
                    f"{current}[v{i}]xfade=transition=fade:duration={transition_duration}:offset=0[vout{i}]"
                )
            else:
                filter_parts.append(
                    f"[vout{i-1}][v{i}]xfade=transition=fade:duration={transition_duration}:offset=0[vout{i}]"
                )
            current = f"[vout{i}]"
        
        filter_complex = ";".join(filter_parts)
        
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", f"[vout{len(video_paths)-1}]",
            "-c:v", "libx264", "-preset", "fast",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
    
    # Get final duration
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        output_path
    ]
    duration_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    return float(duration_result.stdout.strip())

# ===============================
# MAIN ENDPOINT
# ===============================
@app.post("/convert")
def convert(data: ConvertRequest):

    uid = str(uuid.uuid4())
    job_id = uid[:8]
    
    logger.info(f"[{job_id}] ===== START RENDER =====")
    logger.info(f"[{job_id}] Videos: {len(data.drive_urls)}")
    logger.info(f"[{job_id}] Text animation: {data.text_animation}")
    logger.info(f"[{job_id}] Video transition: {data.video_transition}")
    logger.info(f"[{job_id}] Music: {'Yes' if data.music_url else 'No'}")

    # ---------- STEP 1: FONT SELECTION ----------
    font_name = data.font.strip()
    if not font_name.lower().endswith(".ttf"):
        font_name += ".ttf"

    if font_name in SYSTEM_FONTS:
        font_path = SYSTEM_FONTS[font_name]
    else:
        font_path = SYSTEM_FONTS[DEFAULT_FONT]
    
    if not os.path.exists(font_path):
        raise HTTPException(status_code=500, detail=f"Font not found: {font_path}")
    
    logger.info(f"[{job_id}] Font: {font_path}")

    # ---------- STEP 2: TEXT PROCESSING ----------
    import unicodedata
    
    clean_text = data.text
    clean_text = ''.join(char for char in clean_text 
                        if unicodedata.category(char)[0] != 'C' or char in '\n\r\t')
    clean_text = ''.join(char for char in clean_text 
                        if unicodedata.category(char)[0] not in ['So', 'Sk'])
    clean_text = ' '.join(clean_text.split())
    
    wrapped_lines = smart_wrap(clean_text, data.font_size, data.max_chars_per_line)
    logger.info(f"[{job_id}] Text lines ({len(wrapped_lines)}): {wrapped_lines}")

    # ---------- STEP 3: DOWNLOAD VIDEOS ----------
    downloaded_videos = []
    
    for idx, url in enumerate(data.drive_urls):
        video_path = f"{TMP_DIR}/input_{uid}_{idx}.webm"
        logger.info(f"[{job_id}] Downloading video {idx+1}/{len(data.drive_urls)}")
        
        try:
            r = requests.get(url, stream=True, timeout=30)
            if r.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Video {idx+1} download failed")
            
            with open(video_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            
            downloaded_videos.append(video_path)
            logger.info(f"[{job_id}] ✓ Video {idx+1} downloaded")
        except Exception as e:
            logger.error(f"[{job_id}] ✗ Video {idx+1} error: {str(e)}")
            raise

    # ---------- STEP 4: DOWNLOAD MUSIC (if provided) ----------
    music_path = None
    if data.music_url:
        music_path = f"{TMP_DIR}/music_{uid}.mp3"
        logger.info(f"[{job_id}] Downloading music")
        
        try:
            r = requests.get(data.music_url, stream=True, timeout=30)
            if r.status_code == 200:
                with open(music_path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                logger.info(f"[{job_id}] ✓ Music downloaded")
            else:
                logger.warning(f"[{job_id}] Music download failed, continuing without")
                music_path = None
        except Exception as e:
            logger.warning(f"[{job_id}] Music error: {str(e)}, continuing without")
            music_path = None

    # ---------- STEP 5: CONCATENATE VIDEOS ----------
    target_width = 1080
    target_height = 1350 if data.format == "4:5" else (1920 if data.format == "9:16" else 1080)
    
    concat_video = f"{TMP_DIR}/concat_{uid}.mp4"
    
    logger.info(f"[{job_id}] Concatenating videos with transition: {data.video_transition}")
    video_duration = concatenate_videos(
        downloaded_videos, 
        data.video_transition,
        data.transition_duration,
        concat_video,
        target_width,
        target_height
    )
    logger.info(f"[{job_id}] ✓ Videos concatenated, duration: {video_duration}s")

    # ---------- STEP 6: ADD TEXT WITH ANIMATION ----------
    logger.info(f"[{job_id}] Adding animated text")
    
    # Calculate text positions
    if data.text_position == "center":
        y_base = (target_height // 2) - (len(wrapped_lines) * data.font_size) // 2
    elif data.text_position == "bottom":
        y_base = target_height - 140 - (len(wrapped_lines) * int(data.font_size * 1.2))
    else:  # top
        y_base = 120
    
    y_base += data.text_offset
    line_height = int(data.font_size * 1.2)
    
    # Build drawtext filters with animations
    drawtext_filters = []
    for i, line in enumerate(wrapped_lines):
        y_pos = y_base + (i * line_height)
        dt = build_text_animation(
            line, font_path, data.font_size, y_pos,
            data.text_animation, data.animation_duration, video_duration
        )
        drawtext_filters.append(dt)
    
    vf = ",".join(drawtext_filters)
    
    output_video = f"{TMP_DIR}/output_{uid}.mp4"
    
    # ---------- STEP 7: RENDER WITH TEXT & MUSIC ----------
    if music_path:
        logger.info(f"[{job_id}] Rendering with text + music")
        
        # Mix original audio with music
        cmd = [
            "ffmpeg", "-y",
            "-i", concat_video,
            "-i", music_path,
            "-filter_complex",
            f"[0:v]{vf}[vout];"
            f"[1:a]volume={data.music_volume}[music];"
            f"[0:a][music]amix=inputs=2:duration=shortest[aout]",
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-c:a", "aac",
            "-b:a", "192k",
            output_video
        ]
    else:
        logger.info(f"[{job_id}] Rendering with text only")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", concat_video,
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-c:a", "copy",
            output_video
        ]

    logger.info(f"[{job_id}] FFmpeg command: {' '.join(cmd[:10])}...")

    env = os.environ.copy()
    env['LC_ALL'] = 'C.UTF-8'
    env['LANG'] = 'C.UTF-8'

    try:
        result = subprocess.run(cmd, check=True, env=env, capture_output=True, text=True, timeout=300)
        logger.info(f"[{job_id}] ✓ Render complete")
    except subprocess.TimeoutExpired:
        logger.error(f"[{job_id}] ✗ FFmpeg timeout")
        raise HTTPException(status_code=500, detail="Render timeout")
    except subprocess.CalledProcessError as e:
        logger.error(f"[{job_id}] ✗ FFmpeg error: {e.stderr[-500:]}")
        raise HTTPException(status_code=500, detail=f"Render failed: {e.stderr[-200:]}")

    # ---------- STEP 8: VERIFY ----------
    if not os.path.exists(output_video):
        raise HTTPException(status_code=500, detail="Output not created")
    
    output_size = os.path.getsize(output_video)
    logger.info(f"[{job_id}] ✓ Output: {output_size} bytes")
    logger.info(f"[{job_id}] ===== COMPLETE =====")

    return {
        "status": "ok",
        "job_id": job_id,
        "download_url": f"/download/{uid}",
        "details": {
            "videos_processed": len(data.drive_urls),
            "text_lines": wrapped_lines,
            "animation": data.text_animation,
            "has_music": music_path is not None,
            "duration": f"{video_duration:.1f}s",
            "size_mb": f"{output_size / 1024 / 1024:.1f}"
        }
    }

# ===============================
# DOWNLOAD
# ===============================
@app.get("/download/{uid}")
def download(uid: str):
    job_id = uid[:8]
    logger.info(f"[{job_id}] Download request")
    
    path = f"{TMP_DIR}/output_{uid}.mp4"
    
    if not os.path.exists(path):
        logger.error(f"[{job_id}] ✗ Not found")
        raise HTTPException(status_code=404)
    
    logger.info(f"[{job_id}] ✓ Serving file")
    return FileResponse(path, media_type="video/mp4", filename="video.mp4")
