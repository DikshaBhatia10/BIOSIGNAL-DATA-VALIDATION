"""
Generates a short, factual plain-language report from the real QC + analysis
results of one pipeline run, using the Gemini API. Mirrors the same idea as
the LLM summary step in the CDAC orchestrator you shared (call an LLM to turn
a JSON result into a readable report) — but using Gemini instead of an
internal endpoint, since that's what your team has access to.

REQUIRES: GEMINI_API_KEY set as an environment variable (get one free at
https://aistudio.google.com/apikey). Model name is configurable via
GEMINI_MODEL — defaults to "gemini-2.5-flash" below, but Google's model
lineup changes over time, so if this default 404s for you, check
https://ai.google.dev for the current model names and set GEMINI_MODEL
yourself rather than editing this file.
"""

from __future__ import annotations

import os
import json


def generate_report(combined_results: dict) -> str:
    """
    combined_results: the real qc_raw / analysis / qc_cleaned dict for one file.
    Returns the report text. Does not invent any values — the prompt explicitly
    instructs the model to only summarize what's in the JSON, same instruction
    style as the CDAC orchestrator's prompt.
    """
    from google import genai

    api_key = os.environ["GEMINI_API_KEY"]  # fail loudly if missing, don't silently skip
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    client = genai.Client(api_key=api_key)

    prompt = (
        "You are summarizing one real run of an EEG signal-quality validation "
        "pipeline for a research assistant. The pipeline ran quality checks on "
        "a raw EEG recording, cleaned it (bandpass filtering + ICA artifact "
        "removal), and ran the same checks again on the cleaned output. "
        "Write a short, factual, plain-language report under 300 words. "
        "Include: which checks passed/failed before and after cleaning, the "
        "overall quality score change, how many ICA components were removed, "
        "and one sentence on whether the cleaning meaningfully improved data "
        "quality based on these specific numbers. Do not invent any values "
        "not present in the JSON below — if something isn't in the data, "
        "don't mention it.\n\n"
        f"Results JSON:\n{json.dumps(combined_results, indent=2, default=str)}"
    )

    response = client.models.generate_content(model=model, contents=prompt)
    return response.text
