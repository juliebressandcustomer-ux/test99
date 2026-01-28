from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import requests
import uuid
import os

app = FastAPI()

TMP_DIR = "/tmp"

class ConvertRequest(BaseModel):
    drive_url: str
    text: str

@app.post("/convert")
def convert_video(data: ConvertRequest):
    file_id = str(uuid.uuid4())

    input_file = f"{TMP_DIR}/input_{file_id}.webm"
    output_file = f"{TMP_DIR}/output_{file_id}.mp4"

    # 1️⃣ Download from Google Drive
    r = requests.get(data.drive_url, stream=True)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Unable to download file from Drive")

    with open(input_file, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    # 2️⃣ FFmpeg convert + text
    ffmpeg_cmd = [
        "ffmpeg", "-y",
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

    subprocess.run(ffmpeg_cmd, check=True)

    # 3️⃣ Build download URL
    download_url = f"/download/{file_id}"

    return {
        "status": "ok",
        "download_url": download_url,
        "file_id": file_id
    }

@app.get("/download/{file_id}")
def download_video(file_id: str):
    output_file = f"{TMP_DIR}/output_{file_id}.mp4"

    if not os.path.exists(output_file):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        output_file,
        media_type="video/mp4",
        filename="mug.mp4"
    )
