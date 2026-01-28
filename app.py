from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess, requests, uuid, os, textwrap

app = FastAPI()

TMP_DIR = "/tmp"
FONT_DIR = "/app/fonts"

# ----------- INPUT MODEL -----------

class ConvertRequest(BaseModel):
    drive_url: str
    text: str
    format: str = "1:1"          # "1:1" or "4:5"
    font: str = "Inter-Bold.ttf"
    font_size: int = 64
    text_position: str = "top"   # top / center / bottom
    animation: str = "fade"      # none / fade / slide / float

# ----------- TEXT WRAP LOGIC -----------

def smart_wrap(text, font_size):
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

# ----------- POSITION -----------

def get_y(position, fmt):
    if fmt == "4:5":
        return {
            "top": "120",
            "center": "(h-text_h)/2",
            "bottom": "h-text_h-160"
        }.get(position, "120")
    return {
        "top": "90",
        "center": "(h-text_h)/2",
        "bottom": "h-text_h-120"
    }.get(position, "90")

# ----------- ANIMATION -----------

def get_alpha(anim):
    if anim in ["fade", "slide"]:
        return "alpha='if(lt(t,0.8),t/0.8,1)'"
    return "alpha=1"

def get_motion(anim):
    if anim == "slide":
        return "y=y+40*(1-t)"
    if anim == "float":
        return "y=y+12*sin(2*PI*t)"
    return "y=y"

# ----------- MAIN ENDPOINT -----------

@app.post("/convert")
def convert(data: ConvertRequest):

    uid = str(uuid.uuid4())
    input_file = f"{TMP_DIR}/in_{uid}.webm"
    output_file = f"{TMP_DIR}/out_{uid}.mp4"

    font_path = f"{FONT_DIR}/{data.font}"
    if not os.path.exists(font_path):
        raise HTTPException(status_code=400, detail="Font not found")

    wrapped = smart_wrap(data.text, data.font_size)
    y_base = get_y(data.text_position, data.format)
    alpha = get_alpha(data.animation)
    motion = get_motion(data.animation)

    scale = "scale=1080:1350" if data.format == "4:5" else "scale=1080:1080"

    # Download video
    r = requests.get(data.drive_url, stream=True)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Download failed")

    with open(input_file, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    drawtext = (
        f"drawtext=text='{wrapped}':"
        f"fontfile={font_path}:"
        f"fontsize={data.font_size}:"
        "fontcolor=white:"
        "line_spacing=14:"
        "x=(w-text_w)/2:"
        f"y={y_base}:"
        "box=1:boxcolor=black@0.65:boxborderw=28:"
        f"{alpha}"
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

# ----------- DOWNLOAD -----------

@app.get("/download/{uid}")
def download(uid: str):
    path = f"{TMP_DIR}/out_{uid}.mp4"
    if not os.path.exists(path):
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="video/mp4", filename="video.mp4")
