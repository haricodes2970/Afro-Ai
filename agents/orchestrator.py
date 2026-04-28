import os
import re
import sys

import pyttsx3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.clipboard_agent import get_code_context, set_clipboard_text
from communication.web_search import fetch_docs

_tts = pyttsx3.init()

INTENT_INSTRUCTIONS = {
    "DEV_OPTIMIZE": (
        "Optimize the following code for performance, readability, and best practices. "
        "Return only the improved code with brief inline comments where needed."
    ),
    "DEV_EXPLAIN": (
        "Explain the following code clearly. "
        "Describe what it does, how it works, and any notable patterns or concerns."
    ),
    "DEV_DEBUG": (
        "Identify and fix all bugs in the following code. "
        "Return the corrected code and a short list of changes made."
    ),
}

COMPLETION_MESSAGES = {
    "DEV_OPTIMIZE": "Optimization complete",
    "DEV_EXPLAIN": "Explanation ready",
    "DEV_DEBUG": "Debug complete",
}

LIB_PATTERN = re.compile(
    r'\b(?:import|from)\s+([\w]+)',
    re.MULTILINE,
)

STDLIB_SKIP = {
    "os", "sys", "re", "io", "math", "time", "json", "csv", "abc",
    "copy", "enum", "glob", "gzip", "hmac", "html", "http", "uuid",
    "struct", "string", "shutil", "socket", "signal", "random",
    "pickle", "pathlib", "logging", "hashlib", "functools",
    "datetime", "dataclasses", "contextlib", "collections",
    "threading", "subprocess", "traceback", "typing", "unittest",
    "argparse", "asyncio", "warnings", "weakref", "tempfile",
}


def _speak(text: str) -> None:
    try:
        _tts.say(text)
        _tts.runAndWait()
    except Exception as e:
        print(f"[Orchestrator] TTS error: {e}")


def _extract_libraries(code: str) -> list[str]:
    matches = LIB_PATTERN.findall(code)
    seen = set()
    libs = []
    for lib in matches:
        if lib not in STDLIB_SKIP and lib not in seen:
            seen.add(lib)
            libs.append(lib)
    return libs[:3]  # cap to avoid excess API calls


def _call_llm(prompt: str) -> str:
    # Priority 1: llama_cpp
    try:
        from llama_cpp import Llama
        model_path = os.getenv(
            "LOCAL_MODEL_PATH",
            os.path.join("models", "llama.gguf"),
        )
        llm = Llama(model_path=model_path, n_ctx=4096, n_gpu_layers=20, verbose=False)
        output = llm(prompt, max_tokens=1024, temperature=0)
        return output["choices"][0]["text"].strip()
    except Exception:
        pass

    # Priority 2: Claude (Anthropic)
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if api_key:
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
    except Exception:
        pass

    # Priority 3: Gemini
    try:
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-pro")
            response = model.generate_content(prompt)
            return response.text.strip()
    except Exception:
        pass

    return ""


def _build_prompt(intent_label: str, code: str, docs: str) -> str:
    instruction = INTENT_INSTRUCTIONS.get(intent_label, INTENT_INSTRUCTIONS["DEV_EXPLAIN"])
    parts = [instruction, "\n\n--- CODE ---\n", code]
    if docs:
        parts += ["\n\n--- RELEVANT DOCUMENTATION ---\n", docs]
    return "".join(parts)


class Orchestrator:
    def run_dev_loop(self, intent_label: str) -> None:
        # A — clipboard ingestion
        _speak("Reading clipboard...")
        print("[Orchestrator] Reading clipboard...")
        code = get_code_context()

        if not code:
            print("[Orchestrator] Clipboard is empty or contains no code.")
            _speak("Clipboard is empty.")
            return

        # B — optional documentation fetch
        docs = ""
        libs = _extract_libraries(code)
        if libs:
            _speak("Searching documentation...")
            print(f"[Orchestrator] Fetching docs for: {libs}")
            doc_parts = []
            for lib in libs:
                result = fetch_docs(lib)
                if result:
                    doc_parts.append(f"[{lib}]\n{result}")
            docs = "\n\n".join(doc_parts)

        # C — prompt construction
        prompt = _build_prompt(intent_label, code, docs)

        # D — LLM execution
        _speak("Consulting AI model...")
        print("[Orchestrator] Sending to LLM...")
        llm_response = _call_llm(prompt)

        if not llm_response:
            print("[Orchestrator] LLM returned no response.")
            _speak("No response from AI model.")
            return

        # E — output handling
        set_clipboard_text(llm_response)
        print(f"[Orchestrator] Result copied to clipboard ({len(llm_response)} chars).")

        completion_msg = COMPLETION_MESSAGES.get(intent_label, "Task complete")
        _speak(completion_msg)
        print(f"[Orchestrator] {completion_msg}.")
