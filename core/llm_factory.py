import os
import sys

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o"

REQUEST_TIMEOUT = 30

INTENT_PROVIDER_MAP = {
    "DEV_EXPLAIN": "GROQ",
    "DEV_OPTIMIZE": "GEMINI",
    "DEV_DEBUG": "OPENAI",
}


def _call_groq(system_prompt: str, user_content: str) -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY not set.")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": 2048,
    }
    resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_gemini(system_prompt: str, user_content: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set.")

    url = f"{GEMINI_API_URL}?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_prompt}\n\n{user_content}"}
                ]
            }
        ],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 2048},
    }
    resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_openai(system_prompt: str, user_content: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set.")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": 2048,
    }
    resp = requests.post(OPENAI_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


_PROVIDER_CALLABLES = {
    "GROQ": _call_groq,
    "GEMINI": _call_gemini,
    "OPENAI": _call_openai,
}


class LLMFactory:

    def get_llm(self, intent_label: str):
        provider = INTENT_PROVIDER_MAP.get(intent_label, "OPENAI")
        return _PROVIDER_CALLABLES[provider]

    def call(self, intent_label: str, system_prompt: str, user_content: str) -> str:
        provider = INTENT_PROVIDER_MAP.get(intent_label, "OPENAI")
        fn = _PROVIDER_CALLABLES[provider]
        print(f"[LLMFactory] Routing {intent_label} → {provider}")
        try:
            return fn(system_prompt, user_content)
        except EnvironmentError as e:
            print(f"[LLMFactory] {e}", file=sys.stderr)
            return ""
        except requests.exceptions.RequestException as e:
            print(f"[LLMFactory] API request failed ({provider}): {e}", file=sys.stderr)
            return ""
        except (KeyError, IndexError, ValueError) as e:
            print(f"[LLMFactory] Response parse error ({provider}): {e}", file=sys.stderr)
            return ""
