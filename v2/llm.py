"""Thin wrapper around the Gemini API (google-genai SDK)."""
import json
import os

from google import genai
from google.genai import types


class GeminiLLM:
    def __init__(self, api_key=None, model=None):
        self.client = genai.Client(
            api_key=api_key or os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=60_000),  # fail instead of hanging
        )
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    def text(self, system, user, temperature=0.7):
        r = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=temperature),
        )
        return (r.text or "").strip()

    def json(self, system, user, schema):
        r = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        return json.loads(r.text)
