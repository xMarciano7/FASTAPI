import os
import uuid
import shutil
import threading
import subprocess
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
import whisper

# ---------------- CONFIG ----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STORAGE_INPUT = os.path.join(BASE_DIR, "storage", "input")
STORAGE_TMP = os.path.join(BASE_DIR, "storage", "tmp")
STORAGE_OUTPUT = os.path.join(BASE_DIR, "storage", "output")

os.makedirs(STORAGE_INPUT, exist_ok=True)
os.makedirs(STORAGE_TMP, exist_ok=True)
os.makedirs(STORAGE_OUTPUT, exist_ok=True)

# ---------------- APP ----------------

app = FastAPI()

# ---------------- STATE ----------------

jobs = {}

# ---------------- WHISPER (GLOBAL) ----------------
# IMPORTANTE: cargar UNA sola vez
whisper_model = whisper.load_model("base")

# ---------------- WORKER ----------------

def process_job(job_id: str, input_path: str):
    try:
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["percent"] = 5

        wav_path = os.path.join(STORAGE_TMP, f"{job_id}.wav")

        # 1️⃣ Extraer audio
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                wav_path,
            ],
            check=True,
        )

        jobs[job_id]["percent"] = 25

        # 2️⃣ Whisper
        result = whisper_model.transcribe(wav_path)

        jobs[job_id]["percent"] = 60

        # 3️⃣ Crear subtítulos simples (TXT → placeholder)
        subs_path = os.path.join(STORAGE_TMP, f"{job_id}.txt")
        with open(subs_path, "w", encoding="utf-8") as f:
            f.write(result["text"])

        jobs[job_id]["percent"] = 80

        # 4️⃣ Copiar vídeo final (sin quemar aún)
        output_path = os.path.join(STORAGE_OUTPUT, f"{job_id}.mp4")
        shutil.copy(input_path, output_path)

        jobs[job_id]["output"] = output_path
        jobs[job_id]["percent"] = 100
        jobs[job_id]["status"] = "done"

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["percent"] = 0


# ---------------- ENDPOINTS ----------------

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    input_path = os.path.join(STORAGE_INPUT, f"{job_id}.mp4")

    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    jobs[job_id] = {
        "status": "queued",
        "percent": 0,
        "output": None,
    }

    thread = threading.Thread(
        target=process_job,
        args=(job_id, input_path),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"status": "error", "percent": 0}, status_code=404)

    return {
        "status": job["status"],
        "percent": job.get("percent", 0),
    }


@app.get("/download/{job_id}")
def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return JSONResponse({"error": "Not ready"}, status_code=400)

    return FileResponse(job["output"], media_type="video/mp4")


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
