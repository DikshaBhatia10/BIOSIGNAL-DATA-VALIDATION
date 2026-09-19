"""
A2A-style server for the ECG agent. Same transport note as the EEG agents'
servers — plain FastAPI, matching the same message contract.

Run with: uvicorn server:app --port 9003
"""

import os
from fastapi import FastAPI
from pydantic import BaseModel

from agent import run_check, save_cleaned_csv

app = FastAPI(title="ECG Agent")

MODEL_DIR = os.environ.get("ECG_MODEL_DIR", ".")  # where ecg_autoencoder.pt
# and ecg_threshold.json live — defaults to this folder, override if you
# keep trained models elsewhere.


class ECGRequest(BaseModel):
    file_path: str
    pass_label: str = "raw"
    output_dir: str = "./outputs"


@app.post("/message")
def handle_message(req: ECGRequest):
    try:
        result = run_check(req.file_path, MODEL_DIR, pass_label=req.pass_label)

        cleaned_path = None
        if req.pass_label == "raw" and "cleaned_signal" in result:
            base = os.path.splitext(os.path.basename(req.file_path))[0]
            cleaned_path = save_cleaned_csv(
                result.pop("cleaned_signal"), result["sampling_rate"], req.output_dir, base
            )
            result["cleaned_file"] = cleaned_path

        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


@app.get("/health")
def health():
    return {"status": "ok", "agent": "ecg"}
