import os
import re

import requests

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"
REQUEST_TIMEOUT = 10
MAX_RESPONSE_CHARS = 3000


def _fetch_via_perplexity(query: str, api_key: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": PERPLEXITY_MODEL,
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
    response = requests.post(PERPLEXITY_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def _fetch_via_scrape(query: str) -> str:
    search_url = f"https://docs.python.org/3/search.html?q={requests.utils.quote(query)}&check_keywords=yes&area=default"
    try:
        resp = requests.get(search_url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        # strip HTML tags to get plain text
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'&[a-z]+;', ' ', text)
        text = re.sub(r'\s{2,}', ' ', text).strip()
        # return a reasonable snippet
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
    api_key = os.getenv("PERPLEXITY_API_KEY", "").strip()

    if api_key:
        try:
            result = _fetch_via_perplexity(query, api_key)
            if result:
                return result[:MAX_RESPONSE_CHARS]
        except requests.exceptions.RequestException as e:
            print(f"[WebSearch] Perplexity request failed: {e}. Falling back to scrape.")
        except (KeyError, IndexError, ValueError) as e:
            print(f"[WebSearch] Perplexity parse error: {e}. Falling back to scrape.")

    return _fetch_via_scrape(query)
