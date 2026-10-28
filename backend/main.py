import os
import uuid
import shutil
import subprocess
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Nishflix LK Media API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

BASE = Path(os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")) / "nishflix"
BASE.mkdir(parents=True, exist_ok=True)
MAX_BYTES = 50 * 1024 * 1024
ALLOWED = {".mp4", ".mov", ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".ogg"}

@app.get("/health")
def health():
    return {"ok": True, "service": "Nishflix LK Media API"}

@app.post("/process")
async def process_media(
    file: UploadFile = File(...),
    mode: str = Form(...),
    quality: str = Form("original"),
):
    ext = Path(file.filename or "").suffix.lower()

    if ext not in ALLOWED:
        raise HTTPException(400, "Unsupported file type")

    if mode not in {"video", "audio"}:
        raise HTTPException(400, "Mode must be video or audio")

    if quality not in {"original", "480", "720"}:
        raise HTTPException(400, "Unsupported quality")

    job = uuid.uuid4().hex
    source = BASE / f"{job}{ext}"
    output = BASE / f"{job}_processed.mp3" if mode == "audio" else BASE / f"{job}_processed.mp4"

    try:
        size = 0
        with source.open("wb") as dest:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "Maximum upload size is 50 MB")
                dest.write(chunk)

        if size == 0:
            raise HTTPException(400, "Empty file")

        if mode == "audio":
            cmd = [
                "ffmpeg", "-nostdin", "-v", "error", "-y",
                "-i", str(source), "-vn", "-t", "600",
                "-codec:a", "libmp3lame", "-b:a", "192k",
                str(output),
            ]
        else:
            cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
                   "-i", str(source), "-t", "600"]

            if quality != "original":
                cmd += ["-vf", f"scale=-2:{quality}:force_original_aspect_ratio=decrease"]

            cmd += ["-c:v", "libx264", "-c:a", "aac",
                    "-movflags", "+faststart", str(output)]

        print("INPUT:", source, "OUTPUT:", output, "SAME:", source.resolve() == output.resolve())
        print("FFMPEG CMD:", cmd)
        try:
            result = subprocess.run(
                cmd, check=True, timeout=120,
                capture_output=True, text=True
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(408, "Processing timed out")
        except subprocess.CalledProcessError as exc:
            print("FFmpeg error:", exc.stderr or exc.stdout or str(exc))
            raise HTTPException(400, "Processing failed; check backend logs")

        return {
            "ok": True,
            "download_url": f"/download/{output.name}",
            "filename": output.name,
        }

    except HTTPException:
        raise
    finally:
        await file.close()
        source.unlink(missing_ok=True)

@app.get("/download/{filename}")
def download(filename: str):
    if not filename.endswith((".mp3", ".mp4")) or "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")

    path = BASE / filename
    if not path.is_file():
        raise HTTPException(404, "File expired or not found")

    return FileResponse(
        path,
        filename=filename,
        media_type="audio/mpeg" if filename.endswith(".mp3") else "video/mp4",
        background=None,
    )
