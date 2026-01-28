from fastapi import FastAPI
from pydantic import BaseModel
import subprocess
import requests
import os
import uuid

app = FastAPI()

class ConvertRequest(BaseModel):
    drive_url: str
    text: str

@app.post("/convert")
def convert_video(data: ConvertRequest):
    uid = str(uuid.uuid4())
    input_file = f"/tmp/input_{uid}.webm"
    output_file = f"/tmp/output_{uid}.mp4"

    # 1. Download video
    r = requests.get(data.drive_url, stream=True)
    with open(input_file, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    # 2. FFmpeg command
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_file,
        "-vf",
        f"drawtext=text='{data.text}':"
        "fontcolor=white:fontsize=64:"
        "x=(w-text_w)/2:y=40:"
        "box=1:boxcolor=black@0.6:boxborderw=20",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_file
    ]

    subprocess.run(cmd, check=True)

    return {
        "status": "ok",
        "output_path": output_file
    }
