"""
A2A-style server for the EEG analysis agent. Same transport note as
qc_agent/server.py — plain FastAPI, matching the same message contract.

Run with: uvicorn server:app --port 9002
"""

from fastapi import FastAPI
from pydantic import BaseModel

from agent import clean_eeg

app = FastAPI(title="EEG Analysis Agent")


class AnalysisRequest(BaseModel):
    file_path: str
    output_dir: str = "./outputs"
    eog_channel: str | None = None


@app.post("/message")
def handle_message(req: AnalysisRequest):
    try:
        result = clean_eeg(req.file_path, req.output_dir, eog_channel=req.eog_channel)
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


@app.get("/health")
def health():
    return {"status": "ok", "agent": "eeg-analysis"}
