"""AI Agent: turns a user prompt into a static website.

Uses an LLM (OpenAI-compatible) if OPENAI_API_KEY is set; otherwise falls back
to a smart template generator that produces polished single-page sites.

The streaming entry point (``generate_site_stream``) yields SSE-friendly events
so the caller can surface the model's thinking/reasoning process in real time.
"""
import os
import re
import json
import random
import asyncio
import httpx

LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """You are an expert frontend engineer. The user describes a website they want.
Return ONLY a JSON object with this exact shape:
{
  "title": "Site title",
  "files": {
    "index.html": "<!DOCTYPE html>...full HTML...",
    "styles.css": "...optional CSS...",
    "script.js": "...optional JS..."
  }
}
Rules:
- Produce a complete, beautiful, responsive single-page website.
- index.html must be self-contained but may reference styles.css and script.js.
- Use modern CSS (flex/grid, gradients, animations). Mobile-first.
- No placeholders like lorem ipsum — write real copy fitting the request.
- No external CDN dependencies; inline SVGs/icons instead.
- NEVER use <img src="..."> with external URLs — they will break. Use CSS gradients, inline SVG, or colored divs for any visual/image placeholders.
- Layout rules (CRITICAL):
  * Headings and titles must NOT wrap character-by-character. Add white-space:nowrap to titles, or give the container enough min-width.
  * Use proper line breaks: separate sections with <section> or <div> blocks; use <br> only for intentional line breaks within a line.
  * Each section must have clear vertical spacing (padding/margin) so content is not cramped.
  * The main content container should be full-width or wide (max-width: 960px~1200px centered), never a narrow sidebar that makes text stack vertically.
  * Text paragraphs should have line-height >= 1.6 and max-width around 600-720px for readability.
  * If using a sidebar layout, ensure the sidebar has min-width (e.g. 200px) so text doesn't wrap to one character per line.
- Output valid JSON only, no markdown fences, no commentary."""
