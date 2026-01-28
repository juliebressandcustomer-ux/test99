from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
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
# DEBUG ENDPOINT
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
        "endpoints": {
            "convert": "POST /convert",
            "download": "GET /download/{uid}",
            "debug_fonts": "GET /debug/fonts"
        }
    }

TMP_DIR = "/tmp"
# Use DejaVu fonts - more comprehensive Unicode support
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
    drive_url: str
    text: str
    format: str = "1:1"                 # 1:1 | 4:5
    font: str = DEFAULT_FONT
    font_size: int = 64
    text_position: str = "top"          # top | center | bottom
    text_offset: int = 0                # vertical offset (px)

# ===============================
# SMART WRAP (MAX 2 LINES)
# ===============================
def smart_wrap(text: str, font_size: int) -> str:
    text = text.upper()

    if font_size <= 56:
        width = 22
    elif font_size <= 64:
        width = 18
    elif font_size <= 72:
        width = 15
    else:
        width = 12

    lines = textwrap.wrap(text, width)

    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]

    return "\n".join(lines)

# ===============================
# BASE Y POSITION
# ===============================
def base_y(position: str) -> str:
    if position == "center":
        return "(h-text_h)/2"
    if position == "bottom":
        return "h-text_h-140"
    return "120"  # top

# ===============================
# MAIN ENDPOINT
# ===============================
@app.post("/convert")
def convert(data: ConvertRequest):

    uid = str(uuid.uuid4())
    job_id = uid[:8]  # Short ID for logging
    input_video = f"{TMP_DIR}/input_{uid}.webm"
    output_video = f"{TMP_DIR}/output_{uid}.mp4"
    text_file = f"{TMP_DIR}/text_{uid}.txt"

    logger.info(f"[{job_id}] ===== START RENDER =====")
    logger.info(f"[{job_id}] Full UUID: {uid}")
    logger.info(f"[{job_id}] Payload: {data.dict()}")

    # ---------- STEP 1: FONT SELECTION ----------
    logger.info(f"[{job_id}] STEP 1: Font selection")
    font_name = data.font.strip()
    if not font_name.lower().endswith(".ttf"):
        font_name += ".ttf"

    # Use system font mapping
    if font_name in SYSTEM_FONTS:
        font_path = SYSTEM_FONTS[font_name]
        logger.info(f"[{job_id}] ✓ Font mapped: {font_name} -> {font_path}")
    else:
        logger.warning(f"[{job_id}] ✗ Font {font_name} not found, using default")
        font_path = SYSTEM_FONTS[DEFAULT_FONT]
        logger.info(f"[{job_id}] ✓ Using default font: {font_path}")
    
    # Verify font exists
    if os.path.exists(font_path):
        logger.info(f"[{job_id}] ✓ Font file verified on disk")
    else:
        logger.error(f"[{job_id}] ✗ CRITICAL: Font file NOT FOUND at {font_path}")

    # ---------- STEP 2: TEXT PROCESSING ----------
    logger.info(f"[{job_id}] STEP 2: Text processing")
    logger.info(f"[{job_id}] Raw input text: {repr(data.text)}")
    logger.info(f"[{job_id}] Text bytes: {data.text.encode('utf-8').hex()}")
    
    # Remove ONLY invisible/control characters, keep emojis and accented characters
    import unicodedata
    
    clean_text = data.text
    # Remove zero-width characters, control characters, but keep printable Unicode (including emojis)
    clean_text = ''.join(char for char in clean_text 
                        if unicodedata.category(char)[0] != 'C' or char in '\n\r\t')
    # Remove extra spaces
    clean_text = ' '.join(clean_text.split())
    
    logger.info(f"[{job_id}] Clean text: {repr(clean_text)}")
    logger.info(f"[{job_id}] Clean text bytes: {clean_text.encode('utf-8').hex()}")
    
    # Don't convert to uppercase if there are emojis (they would be lost)
    has_emoji = any(ord(char) > 127 for char in clean_text)
    
    if has_emoji:
        # Keep original case to preserve emojis
        wrapped_text = '\n'.join(textwrap.wrap(clean_text, width=18 if data.font_size <= 64 else 15))
        logger.info(f"[{job_id}] Emoji detected, keeping original case")
    else:
        # Use normal smart_wrap with uppercase
        wrapped_text = smart_wrap(clean_text, data.font_size)
    
    logger.info(f"[{job_id}] Wrapped text: {repr(wrapped_text)}")
    
    # Create ASS subtitle file instead of plain text
    # ASS format handles newlines much better than drawtext
    ass_file = f"{TMP_DIR}/subtitle_{uid}.ass"
    
    # Replace \n with \N for ASS format (proper line break)
    ass_text = wrapped_text.replace('\n', '\\N')
    
    # Calculate vertical position based on text_position
    video_height = 1350 if data.format == "4:5" else 1080
    
    if data.text_position == "top":
        alignment = 8  # Top center
        margin_v = 120 + data.text_offset
    elif data.text_position == "center":
        alignment = 5  # Middle center
        margin_v = video_height // 2 + data.text_offset
    else:  # bottom
        alignment = 2  # Bottom center
        margin_v = 140 + data.text_offset
    
    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: {video_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{data.font_size},&H00FFFFFF,&H000000FF,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,{alignment},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:99:59.99,Default,,0,0,0,,{ass_text}
"""
    
    with open(ass_file, "w", encoding="utf-8") as f:
        f.write(ass_content)
    
    logger.info(f"[{job_id}] ASS subtitle created: {ass_file}")
    logger.info(f"[{job_id}] Position: {data.text_position}, Alignment: {alignment}, MarginV: {margin_v}")
    logger.info(f"[{job_id}] ASS text: {ass_text}")

    # ---------- STEP 3: VIDEO DOWNLOAD ----------
    logger.info(f"[{job_id}] STEP 3: Downloading video")
    logger.info(f"[{job_id}] URL: {data.drive_url}")
    
    try:
        r = requests.get(data.drive_url, stream=True, timeout=30)
        if r.status_code != 200:
            logger.error(f"[{job_id}] ✗ Video download failed: HTTP {r.status_code}")
            raise HTTPException(status_code=400, detail="Video download failed")

        with open(input_video, "wb") as f:
            total_bytes = 0
            for chunk in r.iter_content(8192):
                f.write(chunk)
                total_bytes += len(chunk)
        
        logger.info(f"[{job_id}] ✓ Video downloaded: {total_bytes} bytes")
        logger.info(f"[{job_id}] ✓ Saved to: {input_video}")
    except Exception as e:
        logger.error(f"[{job_id}] ✗ Download error: {str(e)}")
        raise

    # ---------- STEP 4: FFMPEG FILTER CONSTRUCTION ----------
    logger.info(f"[{job_id}] STEP 4: Building FFmpeg filters")
    
    scale = "scale=1080:1350" if data.format == "4:5" else "scale=1080:1080"
    
    # Use ASS subtitles instead of drawtext - much more reliable for multiline text
    vf = f"{scale},subtitles={ass_file}"
    
    logger.info(f"[{job_id}] Scale filter: {scale}")
    logger.info(f"[{job_id}] Using ASS subtitle file: {ass_file}")
    logger.info(f"[{job_id}] Complete filter:")
    logger.info(f"[{job_id}] {vf}")

    # ---------- STEP 5: FFMPEG EXECUTION ----------
    logger.info(f"[{job_id}] STEP 5: Running FFmpeg")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_video
    ]

    logger.info(f"[{job_id}] FFmpeg command:")
    logger.info(f"[{job_id}] {' '.join(cmd)}")

    # Force UTF-8 encoding for subprocess
    env = os.environ.copy()
    env['LC_ALL'] = 'C.UTF-8'
    env['LANG'] = 'C.UTF-8'

    try:
        result = subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
        logger.info(f"[{job_id}] ✓ FFmpeg completed successfully")
        if result.stderr:
            logger.info(f"[{job_id}] FFmpeg stderr (last 500 chars): {result.stderr[-500:]}")
    except subprocess.CalledProcessError as e:
        logger.error(f"[{job_id}] ✗ FFmpeg failed with code {e.returncode}")
        logger.error(f"[{job_id}] FFmpeg stderr: {e.stderr}")
        raise

    # ---------- STEP 6: VERIFY OUTPUT ----------
    logger.info(f"[{job_id}] STEP 6: Verifying output")
    
    if os.path.exists(output_video):
        output_size = os.path.getsize(output_video)
        logger.info(f"[{job_id}] ✓ Output file created: {output_size} bytes")
        logger.info(f"[{job_id}] ✓ Output path: {output_video}")
    else:
        logger.error(f"[{job_id}] ✗ Output file NOT created!")

    logger.info(f"[{job_id}] ===== RENDER COMPLETE =====")

    return {
        "status": "ok",
        "job_id": job_id,
        "download_url": f"/download/{uid}"
    }

# ===============================
# DOWNLOAD
# ===============================
@app.get("/download/{uid}")
def download(uid: str):
    job_id = uid[:8]
    logger.info(f"[{job_id}] Download request received")
    
    path = f"{TMP_DIR}/output_{uid}.mp4"
    
    if not os.path.exists(path):
        logger.error(f"[{job_id}] ✗ File not found: {path}")
        raise HTTPException(status_code=404)
    
    file_size = os.path.getsize(path)
    logger.info(f"[{job_id}] ✓ Serving file: {file_size} bytes")
    
    return FileResponse(path, media_type="video/mp4", filename="video.mp4")
