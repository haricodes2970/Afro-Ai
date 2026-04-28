import os
import sys

from dotenv import load_dotenv

load_dotenv()

# --- dependency detection ---

try:
    from llama_cpp import Llama
    _llama_available = True
except ImportError:
    _llama_available = False

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    _langchain_available = True
except ImportError:
    _langchain_available = False
    if not _llama_available:
        print(
            "[IntentRouter] LangChain not installed. Using keyword routing.\n"
            "  pip install langchain langchain-openai langchain-core"
        )

# llm_mode: LLAMA_CPP > LANGCHAIN > KEYWORD
if _llama_available:
    _llm_mode = "LLAMA_CPP"
elif _langchain_available:
    _llm_mode = "LANGCHAIN"
else:
    _llm_mode = "KEYWORD"

print(f"[IntentRouter] Mode: {_llm_mode}")

# ---

VALID_LABELS = {"FILE_OPS", "PROCESS_OPS", "CALENDAR_OPS", "SYSTEM_QUERY", "UNKNOWN"}

FILE_OP_KEYWORDS = {
    "delete": "DELETE",
    "remove": "DELETE",
    "sort": "SORT",
    "organise": "SORT",
    "organize": "SORT",
    "clean": "CLEAN",
    "cleanup": "CLEAN",
    "rename": "RENAME",
}

SYSTEM_PROMPT = (
    "You are an intent classifier. Classify the user input into exactly one label.\n"
    "Output ONLY the label — uppercase, no punctuation, no explanation.\n\n"
    "Labels:\n"
    "FILE_OPS — file creation, deletion, sorting, moving, renaming, downloads, documents\n"
    "PROCESS_OPS — killing, stopping, launching, managing processes or applications\n"
    "CALENDAR_OPS — scheduling, meetings, reminders, events, dates, times\n"
    "SYSTEM_QUERY — system info, CPU, RAM, battery, network, status queries\n"
    "UNKNOWN — anything else"
)

_USE_OPENAI = bool(os.getenv("OPENAI_API_KEY", "").strip())


def _build_llm():
    if _llm_mode == "LLAMA_CPP":
        model_path = os.getenv(
            "LOCAL_MODEL_PATH",
            os.path.join("models", "llama.gguf"),
        )
        try:
            print(f"[IntentRouter] Loading llama.cpp model: {model_path}")
            return Llama(
                model_path=model_path,
                n_ctx=512,
                n_gpu_layers=20,
                verbose=False,
            )
        except Exception as e:
            print(f"[IntentRouter] llama.cpp load failed: {e}. Falling back.", file=sys.stderr)
            return None

    if _llm_mode == "LANGCHAIN":
        if _USE_OPENAI:
            try:
                return ChatOpenAI(model="gpt-3.5-turbo", temperature=0)
            except Exception as e:
                print(f"[IntentRouter] ChatOpenAI init failed: {e}.", file=sys.stderr)
                return None
        else:
            try:
                from langchain_community.llms import LlamaCpp
                model_path = os.getenv(
                    "LOCAL_MODEL_PATH",
                    os.path.expanduser("~/models/mistral-7b-instruct.Q4_K_M.gguf"),
                )
                print(f"[IntentRouter] LangChain local mode — loading: {model_path}")
                return LlamaCpp(
                    model_path=model_path,
                    temperature=0,
                    max_tokens=16,
                    n_ctx=512,
                    n_gpu_layers=20,
                    verbose=False,
                )
            except Exception as e:
                print(f"[IntentRouter] LangChain local LLM failed: {e}.", file=sys.stderr)
                return None

    return None


_llm = _build_llm()


def _keyword_route(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ("file", "sort", "rename", "delete", "folder", "download", "document")):
        return "FILE_OPS"
    if any(k in lower for k in ("kill", "stop", "process", "optimize", "terminate", "launch")):
        return "PROCESS_OPS"
    if any(k in lower for k in ("schedule", "meeting", "calendar", "remind", "event", "appointment")):
        return "CALENDAR_OPS"
    if any(k in lower for k in ("cpu", "ram", "memory", "battery", "network", "status", "usage")):
        return "SYSTEM_QUERY"
    return "UNKNOWN"


def _route_llama_cpp(text: str) -> str:
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"User: {text.strip()}\n"
        "Label:"
    )
    output = _llm(
        prompt,
        max_tokens=8,
        temperature=0,
        stop=["\n", " ", "."],
    )
    label = output["choices"][0]["text"].strip().upper()
    return label if label in VALID_LABELS else _keyword_route(text)


def _route_langchain(text: str) -> str:
    if _USE_OPENAI:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=text.strip()),
        ]
        response = _llm.invoke(messages)
        label = response.content.strip().upper()
    else:
        prompt = f"{SYSTEM_PROMPT}\n\nUser: {text.strip()}\nLabel:"
        raw = _llm.invoke(prompt)
        label = (raw.strip() if isinstance(raw, str) else raw.content.strip()).upper().split()[0]
    return label if label in VALID_LABELS else _keyword_route(text)


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

    operation_type = _extract_operation(transcribed_text)
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


class IntentRouter:
    def __init__(self):
        self._llm = _llm
        self._llm_mode = _llm_mode

    def route(self, transcribed_text: str) -> str:
        if not transcribed_text or not transcribed_text.strip():
            return "UNKNOWN"

        label = "UNKNOWN"

        try:
            if self._llm_mode == "LLAMA_CPP" and self._llm is not None:
                label = _route_llama_cpp(transcribed_text)

            elif self._llm_mode == "LANGCHAIN" and self._llm is not None:
                label = _route_langchain(transcribed_text)

            else:
                label = _keyword_route(transcribed_text)

        except Exception as e:
            print(f"[IntentRouter error] {e}", file=sys.stderr)
            label = _keyword_route(transcribed_text)

        if label not in VALID_LABELS:
            label = _keyword_route(transcribed_text)

        if label == "FILE_OPS":
            _dispatch_file_ops(transcribed_text)

        return label
