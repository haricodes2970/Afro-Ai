import os
import re

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama3-8b-8192"
REQUEST_TIMEOUT = 10
MAX_RESPONSE_CHARS = 3000


def _fetch_via_groq(query: str, api_key: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Summarize the official documentation for: {query}. "
                    "Focus on key functions, usage patterns, and version notes. "
                    "Be concise."
                ),
            }
        ],
        "max_tokens": 512,
        "temperature": 0,
    }
    response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def _fetch_via_scrape(query: str) -> str:
    search_url = (
        f"https://docs.python.org/3/search.html"
        f"?q={requests.utils.quote(query)}&check_keywords=yes&area=default"
    )
    try:
        resp = requests.get(search_url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'&[a-z]+;', ' ', text)
        text = re.sub(r'\s{2,}', ' ', text).strip()
        idx = text.lower().find(query.lower())
        if idx != -1:
            start = max(0, idx - 200)
            snippet = text[start:start + MAX_RESPONSE_CHARS]
        else:
            snippet = text[:MAX_RESPONSE_CHARS]
        return snippet
    except Exception as e:
        return f"[WebSearch] Scrape failed: {e}"


def fetch_docs(query: str) -> str:
    if not query or not query.strip():
        return ""

    query = query.strip()
    api_key = os.getenv("GROQ_API_KEY", "").strip()

    if api_key:
        try:
            result = _fetch_via_groq(query, api_key)
            if result:
                return result[:MAX_RESPONSE_CHARS]
        except requests.exceptions.RequestException as e:
            print(f"[WebSearch] Groq request failed: {e}. Falling back to scrape.")
        except (KeyError, IndexError, ValueError) as e:
            print(f"[WebSearch] Groq parse error: {e}. Falling back to scrape.")

    return _fetch_via_scrape(query)
