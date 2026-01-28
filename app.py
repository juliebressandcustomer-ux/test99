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

TMP_DIR = "/tmp"
FONT_DIR = "/app/fonts"
DEFAULT_FONT = "Arial-Bold.ttf"  # Plus fiable pour l'encodage

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
    input_video = f"{TMP_DIR}/input_{uid}.webm"
    output_video = f"{TMP_DIR}/output_{uid}.mp4"
    text_file = f"{TMP_DIR}/text_{uid}.txt"

    logger.info(f"START render {uid}")
    logger.info(f"Payload: {data.dict()}")

    # ---------- FONT SAFE ----------
    font_name = data.font.strip()
    if not font_name.lower().endswith(".ttf"):
        font_name += ".ttf"

    font_path = f"{FONT_DIR}/{font_name}"
    if not os.path.exists(font_path):
        logger.warning("Font not found, fallback to default")
        font_path = f"{FONT_DIR}/{DEFAULT_FONT}"

    # ---------- TEXT ----------
    # Clean text: remove any invisible/special characters
    clean_text = data.text.encode('ascii', 'ignore').decode('ascii')
    wrapped_text = smart_wrap(clean_text, data.font_size)
    
    # Escape special characters for FFmpeg
    escaped_text = wrapped_text.replace(":", "\\:").replace("'", "\\'")

    logger.info("Final text:")
    logger.info(wrapped_text)

    # ---------- DOWNLOAD VIDEO ----------
    r = requests.get(data.drive_url, stream=True)
    if r.status_code != 200:
        logger.error("Video download failed")
        raise HTTPException(status_code=400, detail="Video download failed")

    with open(input_video, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    logger.info("Video downloaded")

    # ---------- FILTERS ----------
    scale = "scale=1080:1350" if data.format == "4:5" else "scale=1080:1080"
    y_expr = f"{base_y(data.text_position)}+({data.text_offset})"

    drawtext = (
        f"drawtext=text='{escaped_text}':"
        f"fontfile='{font_path}':"
        f"fontsize={data.font_size}:"
        "fontcolor=white:"
        "borderw=2:"
        "bordercolor=white:"
        "line_spacing=14:"
        "x=(w-text_w)/2:"
        f"y={y_expr}:"
        "text_align=C"
    )

    vf = f"{scale},{drawtext}"

    cmd = [
        "ffmpeg", "-y",
        "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_video
    ]

    logger.info("Running FFmpeg")
    logger.info(" ".join(cmd))

    # Force UTF-8 encoding for subprocess
    env = os.environ.copy()
    env['LC_ALL'] = 'C.UTF-8'
    env['LANG'] = 'C.UTF-8'

    subprocess.run(cmd, check=True, env=env)

    logger.info("Render finished")

    return {
        "status": "ok",
        "download_url": f"/download/{uid}"
    }

# ===============================
# DOWNLOAD
# ===============================
@app.get("/download/{uid}")
def download(uid: str):
    path = f"{TMP_DIR}/output_{uid}.mp4"
    if not os.path.exists(path):
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="video/mp4", filename="video.mp4")
