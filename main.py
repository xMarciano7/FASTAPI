import os
import uuid
import json
import threading
import subprocess
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yjcuza-my-site-teyd1jsn-othmanebenbrahim12.wix-vibe.com"],  # o el dominio de tu web
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE = os.path.join(BASE_DIR, "storage")
INPUT = os.path.join(STORAGE, "input")
TMP = os.path.join(STORAGE, "tmp")
OUTPUT = os.path.join(STORAGE, "output")

os.makedirs(INPUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

jobs = {}
presets = {}

# ---------- PRESET (NUEVO) ----------
@app.post("/preset")
async def save_preset(preset: dict):
    preset_id = str(uuid.uuid4())
    presets[preset_id] = preset
    return {"preset_id": preset_id}

# ---------- UPLOAD ----------
@app.post("/upload")
async def upload(file: UploadFile = File(...), preset_id: str = ""):
    job_id = str(uuid.uuid4())
    input_path = os.path.join(INPUT, f"{job_id}.mp4")

    with open(input_path, "wb") as f:
        f.write(await file.read())

    jobs[job_id] = {
        "status": "processing",
        "input": input_path,
        "preset": presets.get(preset_id, {})
    }

    threading.Thread(target=process_job, args=(job_id,)).start()
    return {"job_id": job_id}

# ---------- STATUS ----------
@app.get("/status/{job_id}")
def status(job_id: str):
    job = jobs.get(job_id)

    if not job:
        return {"status": "processing", "percent": 0}

    return {
        "status": job.get("status", "processing"),
        "percent": job.get("percent", 0),
    }


# ---------- DOWNLOAD ----------
@app.get("/download/{job_id}")
def download(job_id: str):
    path = os.path.join(OUTPUT, f"{job_id}.mp4")
    if not os.path.exists(path):
        return JSONResponse({"error": "file not ready"}, status_code=404)
    return FileResponse(path, media_type="video/mp4", filename="clip.mp4")

# ---------- PIPELINE ----------
def process_job(job_id: str):
    try:
        job = jobs[job_id]
        preset = job["preset"]
        video = job["input"]

        wav = os.path.join(TMP, f"{job_id}.wav")
        json_out = os.path.join(TMP, f"{job_id}.json")
        ass = os.path.join(TMP, f"{job_id}.ass")
        out = os.path.join(OUTPUT, f"{job_id}.mp4")

        # -------- AUDIO --------
        subprocess.run([
            "ffmpeg", "-y", "-i", video,
            "-t", "25",
            "-ac", "1", "-ar", "16000", wav
        ], check=True)

        # -------- WHISPER --------
        subprocess.run([
            "whisper", wav,
            "--model", "base",
            "--word_timestamps", "True",
            "--output_format", "json",
            "--output_dir", TMP,
        ], check=True)

        # -------- LOAD WORDS --------
        with open(json_out, "r", encoding="utf-8") as f:
            data = json.load(f)

        words = []
        for seg in data["segments"]:
            for w in seg["words"]:
                words.append({
                    "text": w["word"].strip(),
                    "start": w["start"],
                    "end": w["end"]
                })

        # -------- PRESET VALUES --------
        font = preset.get("font", "Poppins ExtraBold")
        size = preset.get("size", 130)
        color = preset.get("primary_color", "&H0000FFFF")
        outline = preset.get("outline", 6)
        align = preset.get("alignment", 2)
        margin_v = preset.get("margin_v", 350)
        max_words = preset.get("max_words", 2)

        # -------- ASS HEADER --------
        with open(ass, "w", encoding="utf-8") as f:
            f.write(f"""
[Script Info]
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{color},{color},&H00000000,&H00000000,1,0,1,{outline},0,{align},50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Text
""")

            # -------- WORD GROUPING --------
            i = 0
            while i < len(words):
                group = words[i:i + max_words]
                text = " ".join(w["text"] for w in group)
                start = group[0]["start"]
                end = group[-1]["end"]

                f.write(
                    f"Dialogue: 0,{sec(start)},{sec(end)},Default,,0,0,0,,{text}\n"
                )
                i += max_words

        # -------- BURN SUBS --------
        subprocess.run([
            "ffmpeg", "-y", "-i", video,
            "-t", "25",
            "-vf", f"ass={ass}",
            out
        ], check=True)

        jobs[job_id]["status"] = "done"

    except Exception as e:
        jobs[job_id]["status"] = "error"
        print("ERROR:", e)

def sec(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"
