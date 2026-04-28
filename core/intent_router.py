import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ── Dependency detection ──────────────────────────────────────────────────────

try:
    from llama_cpp import Llama
    _llama_available = True
except ImportError:
    _llama_available = False

try:
    import groq as _groq_lib
    _groq_available = bool(os.getenv("GROQ_API_KEY", "").strip())
except ImportError:
    _groq_available = False

try:
    import google.generativeai as _genai
    _gemini_available = bool(os.getenv("GEMINI_API_KEY", "").strip())
except ImportError:
    _gemini_available = False

# Priority: LLAMA_CPP → GROQ → GEMINI → KEYWORD
if _llama_available:
    _llm_mode = "LLAMA_CPP"
elif _groq_available:
    _llm_mode = "GROQ"
elif _gemini_available:
    _llm_mode = "GEMINI"
else:
    _llm_mode = "KEYWORD"

print(f"[IntentRouter] Mode: {_llm_mode}")

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_LABELS = {
    "FILE_OPS", "PROCESS_OPS", "CALENDAR_OPS", "SYSTEM_QUERY",
    "DEV_OPTIMIZE", "DEV_EXPLAIN", "DEV_DEBUG",
    "ENTER_FOCUS", "EXIT_FOCUS",
    "UNKNOWN",
}

FILE_OP_KEYWORDS = {
    "delete":   "DELETE",
    "remove":   "DELETE",
    "sort":     "SORT",
    "organise": "SORT",
    "organize": "SORT",
    "clean":    "CLEAN",
    "cleanup":  "CLEAN",
    "rename":   "RENAME",
}

SYSTEM_PROMPT = (
    "You are an intent classifier. Classify the user input into exactly one label.\n"
    "Output ONLY the label — uppercase, no punctuation, no explanation.\n\n"
    "Labels:\n"
    "FILE_OPS — file creation, deletion, sorting, moving, renaming, downloads, documents\n"
    "PROCESS_OPS — killing, stopping, launching, managing processes or applications\n"
    "CALENDAR_OPS — scheduling, meetings, reminders, events, dates, times\n"
    "SYSTEM_QUERY — system info, CPU, RAM, battery, network, status queries\n"
    "DEV_OPTIMIZE — optimize, improve, refactor, speed up code\n"
    "DEV_EXPLAIN — explain, describe, summarize code\n"
    "DEV_DEBUG — debug, fix, find error, solve bug in code\n"
    "ENTER_FOCUS — activate deep focus mode, start focus, enter focus\n"
    "EXIT_FOCUS — standby, exit focus mode, stop focus, deactivate\n"
    "UNKNOWN — anything else"
)

# ── llama.cpp model (loaded once at import) ───────────────────────────────────

_llm = None

if _llm_mode == "LLAMA_CPP":
    try:
        _model_path = os.getenv("LOCAL_MODEL_PATH", os.path.join("models", "llama.gguf"))
        print(f"[IntentRouter] Loading llama.cpp model: {_model_path}")
        _llm = Llama(model_path=_model_path, n_ctx=512, n_gpu_layers=20, verbose=False)
    except Exception as e:
        print(f"[IntentRouter] llama.cpp load failed: {e} — switching to GROQ/GEMINI/KEYWORD",
              file=sys.stderr)
        _llm = None
        _llm_mode = "GROQ" if _groq_available else ("GEMINI" if _gemini_available else "KEYWORD")
        print(f"[IntentRouter] Mode updated: {_llm_mode}")

# ── Keyword fallback ──────────────────────────────────────────────────────────

def _keyword_route(text: str) -> str:
    lower = text.lower()

    if any(k in lower for k in ("deep focus", "focus mode", "enter focus", "start focus")):
        return "ENTER_FOCUS"
    if any(k in lower for k in ("standby", "exit focus", "stop focus", "leave focus", "deactivate focus")):
        return "EXIT_FOCUS"
    if any(k in lower for k in ("optimize", "refactor", "improve", "speed up")):
        return "DEV_OPTIMIZE"
    if any(k in lower for k in ("explain", "describe", "summarize", "what does")):
        return "DEV_EXPLAIN"
    if any(k in lower for k in ("debug", "fix", "error", "bug", "broken")):
        return "DEV_DEBUG"
    if any(k in lower for k in ("file", "sort", "rename", "delete", "folder", "download", "document")):
        return "FILE_OPS"
    if any(k in lower for k in ("kill", "stop", "process", "terminate", "launch")):
        return "PROCESS_OPS"
    if any(k in lower for k in ("schedule", "meeting", "calendar", "remind", "event", "appointment")):
        return "CALENDAR_OPS"
    if any(k in lower for k in ("cpu", "ram", "memory", "battery", "network", "status", "usage")):
        return "SYSTEM_QUERY"
    return "UNKNOWN"

# ── LLM routing functions ─────────────────────────────────────────────────────

def _route_llama_cpp(text: str) -> str:
    prompt = f"{SYSTEM_PROMPT}\n\nUser: {text.strip()}\nLabel:"
    output = _llm(prompt, max_tokens=8, temperature=0, stop=["\n", " ", "."])
    label  = output["choices"][0]["text"].strip().upper()
    return label if label in VALID_LABELS else _keyword_route(text)


def _route_groq(text: str) -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    client  = _groq_lib.Groq(api_key=api_key)
    resp = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": text.strip()},
        ],
        max_tokens=8,
        temperature=0,
    )
    label = resp.choices[0].message.content.strip().upper().split()[0]
    return label if label in VALID_LABELS else _keyword_route(text)


def _route_gemini(text: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    _genai.configure(api_key=api_key)
    model  = _genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"{SYSTEM_PROMPT}\n\nUser: {text.strip()}\nLabel:"
    resp   = model.generate_content(prompt)
    label  = resp.text.strip().upper().split()[0]
    return label if label in VALID_LABELS else _keyword_route(text)


def _call_router(text: str) -> str:
    """
    Try Groq first, fall back to Gemini, fall back to keyword.
    Used when LLAMA_CPP is not available.
    """
    if _groq_available:
        try:
            return _route_groq(text)
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "quota" in err or "rate" in err:
                print(f"[IntentRouter] Groq quota hit — trying Gemini: {e}", file=sys.stderr)
            else:
                print(f"[IntentRouter] Groq error — trying Gemini: {e}", file=sys.stderr)

    if _gemini_available:
        try:
            return _route_gemini(text)
        except Exception as e:
            print(f"[IntentRouter] Gemini error — keyword fallback: {e}", file=sys.stderr)

    return _keyword_route(text)

# ── File / dev dispatch helpers ───────────────────────────────────────────────

def _extract_operation(text: str) -> str:
    lower = text.lower()
    for keyword, operation in FILE_OP_KEYWORDS.items():
        if keyword in lower:
            return operation
    return "SORT"


def _extract_directory(text: str) -> str:
    import re
    match = re.search(r'[A-Za-z]:[\\\/][\w\s\\\/\-\.]+', text)
    if match:
        return match.group(0).strip()
    for word in text.split():
        if os.path.isdir(word):
            return word
    return os.path.expanduser("~/Downloads")


def _dispatch_file_ops(transcribed_text: str) -> None:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from agents.file_agent import FileAgent
    from core.safety import confirm_action

    operation_type   = _extract_operation(transcribed_text)
    target_directory = _extract_directory(transcribed_text)
    agent = FileAgent()

    if operation_type == "SORT":
        agent.sort(target_directory)
    elif operation_type == "CLEAN":
        agent.clean(target_directory)
    elif operation_type == "RENAME":
        if not confirm_action(f"Rename files in: {target_directory}"):
            print("Operation aborted by user")
            return
        agent.rename(target_directory)
    elif operation_type == "DELETE":
        if not confirm_action(f"Delete files in: {target_directory}"):
            print("Operation aborted by user")
            return
        print(f"[FileAgent] DELETE requested for: {target_directory}")
        print("[FileAgent] Specify exact file_path for deletion.")


def _dispatch_dev_ops(intent_label: str) -> None:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from agents.orchestrator import Orchestrator
    Orchestrator().run_dev_loop(intent_label)

# ── Public interface ──────────────────────────────────────────────────────────

class IntentRouter:
    def route(self, transcribed_text: str) -> str:
        if not transcribed_text or not transcribed_text.strip():
            return "UNKNOWN"

        label = "UNKNOWN"
        try:
            if _llm_mode == "LLAMA_CPP" and _llm is not None:
                label = _route_llama_cpp(transcribed_text)
            else:
                label = _call_router(transcribed_text)
        except Exception as e:
            print(f"[IntentRouter] Routing error — keyword fallback: {e}", file=sys.stderr)
            label = _keyword_route(transcribed_text)

        if label not in VALID_LABELS:
            label = _keyword_route(transcribed_text)

        if label == "FILE_OPS":
            _dispatch_file_ops(transcribed_text)
        elif label in ("DEV_OPTIMIZE", "DEV_EXPLAIN", "DEV_DEBUG"):
            _dispatch_dev_ops(label)

        return label
