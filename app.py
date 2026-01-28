from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess, requests, uuid, os, textwrap

app = FastAPI()

TMP_DIR = "/tmp"
FONT_DIR = "/app/fonts"
DEFAULT_FONT = "Montserrat-Bold.ttf"

# ===============================
# MODELE INPUT
# ===============================

class ConvertRequest(BaseModel):
    drive_url: str
    text: str
    format: str = "1:1"              # 1:1 | 4:5
    font: str = DEFAULT_FONT
    font_size: int = 64
    text_position: str = "top"       # top | center | bottom
    animation: str = "fade"          # none | fade

# ===============================
# UTILS TEXTE
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

def escape_ffmpeg_text(text: str) -> str:
    return (
        text
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("\n", "\\n")
    )

# ===============================
# POSITION TEXTE
# ===============================

def get_y_position(position: str) -> str:
    if position == "center":
        return "(h-text_h)/2"
    if position == "bottom":
        return "h-text_h-140"
    return "120"   # top

# ===============================
# ENDPOINT PRINCIPAL
# ===============================

@app.post("/convert")
def convert(data: ConvertRequest):

    uid = str(uuid.uuid4())
    input_file = f"{TMP_DIR}/input_{uid}.webm"
    output_file = f"{TMP_DIR}/output_{uid}.mp4"

    # ---------- FONT SAFE ----------
    font_name = data.font.strip()
    if not font_name.lower().endswith(".ttf"):
        font_name += ".ttf"

    font_path = f"{FONT_DIR}/{font_name}"
    if not os.path.exists(font_path):
        font_path = f"{FONT_DIR}/{DEFAULT_FONT}"

    # ---------- TEXTE ----------
    wrapped = smart_wrap(data.text, data.font_size)
    wrapped = escape_ffmpeg_text(wrapped)

    y_pos = get_y_position(data.text_position)

    scale = "scale=1080:1350" if data.format == "4:5" else "scale=1080:1080"

    # ---------- DOWNLOAD VIDEO ----------
    r = requests.get(data.drive_url, stream=True)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Video download failed")

    with open(input_file, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    # ---------- DRAWTEXT ----------
    drawtext = (
        f"drawtext=text='{wrapped}':"
        f"fontfile={font_path}:"
        f"fontsize={data.font_size}:"
        "fontcolor=white:"
        "line_spacing=18:"
        "x=(w-text_w)/2:"
        f"y={y_pos}:"
        "box=1:"
        "boxcolor=black@0.7:"
        "boxborderw=36:"
        "alpha='if(lt(t,0.6),t/0.6,1)'"
    )

    vf = f"{scale},{drawtext}"

    subprocess.run([
        "ffmpeg", "-y",
        "-i", input_file,
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_file
    ], check=True)

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
