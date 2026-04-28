import ast
import json
import os
import re
import sys

import pyttsx3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.clipboard_agent import get_code_context, set_clipboard_text
from agents.os_agent import OSAgent
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

LIB_PATTERN = re.compile(r'\b(?:import|from)\s+([\w]+)', re.MULTILINE)

STDLIB_SKIP = {
    "os", "sys", "re", "io", "math", "time", "json", "csv", "abc",
    "copy", "enum", "glob", "gzip", "hmac", "html", "http", "uuid",
    "struct", "string", "shutil", "socket", "signal", "random",
    "pickle", "pathlib", "logging", "hashlib", "functools",
    "datetime", "dataclasses", "contextlib", "collections",
    "threading", "subprocess", "traceback", "typing", "unittest",
    "argparse", "asyncio", "warnings", "weakref", "tempfile",
}

_USERNAME = os.environ.get("USERNAME", os.environ.get("USER", "User"))
_HOME     = os.path.expanduser("~").replace("\\", "/")

# ── Knowledge Base ────────────────────────────────────────────────────────────

_KB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "config", "knowledge_base.json")
)

_FALLBACK_TOOLS = [
    {"name": "create_folder",  "arguments": ["path"],                          "description": "Creates a new folder at the specified filesystem path"},
    {"name": "delete_item",    "arguments": ["path"],                          "description": "Deletes a file or folder after user confirmation"},
    {"name": "sort_directory", "arguments": ["path", "criteria"],              "description": "Moves directory files into categorized subfolders by type"},
    {"name": "install_app",    "arguments": ["app_name"],                      "description": "Installs an application via winget or chocolatey package manager"},
    {"name": "open_vscode",    "arguments": ["filepath"],                      "description": "Launches VS Code optionally opening a specified file or folder"},
    {"name": "focus_editor",   "arguments": [],                                "description": "Brings the VS Code window to the foreground"},
    {"name": "type_code",      "arguments": ["text"],                          "description": "Types text into the currently focused VS Code editor"},
    {"name": "talk_back",      "arguments": ["message"],                       "description": "Asks user for clarification or provides feedback"},
    {"name": "upgrade_yourself","arguments": ["target_path", "code_snippet"],  "description": "Modifies Afro's codebase and triggers self-restart"},
]


def _load_knowledge_base() -> list[dict]:
    try:
        with open(_KB_PATH, "r", encoding="utf-8") as f:
            tools = json.load(f).get("tools", [])
        print(f"[Orchestrator] Loaded {len(tools)} tool(s) from knowledge_base.json")
        return tools
    except Exception as e:
        print(f"[Orchestrator] knowledge_base.json load failed — using fallback: {e}", file=sys.stderr)
        return _FALLBACK_TOOLS


_TOOLS_KB   = _load_knowledge_base()
_TOOLS_JSON = json.dumps(_TOOLS_KB, indent=2)

# Braces in the embedded JSON must be escaped so DIRECTOR_PROMPT.format() works.
_TOOLS_JSON_ESC = _TOOLS_JSON.replace("{", "{{").replace("}", "}}")

# Whitelist derived from the knowledge base — no hardcoded names.
_ALLOWED_TOOLS: set[str] = {t["name"] for t in _TOOLS_KB}

# ── Director Prompt ───────────────────────────────────────────────────────────

DIRECTOR_PROMPT = (
    "[ROLE]\n"
    "You are the Director Agent for Afro, a Windows OS Automator.\n"
    "Convert natural language voice commands into structured, executable actions.\n"
    "\n"
    "[AVAILABLE TOOLS]\n"
    "You have access to the following tools only:\n"
    + _TOOLS_JSON_ESC +
    "\n"
    "Only use tools listed above. Do not invent or reference any other tool.\n"
    "\n"
    "[STRICT RULES]\n"
    "- OUTPUT ONLY VALID JSON — no markdown, no explanations, no code fences\n"
    "- Always return a JSON ARRAY (even for a single action)\n"
    "- Each item MUST have \"tool\" and \"args\" keys\n"
    "- \"tool\" MUST be one of the names in [AVAILABLE TOOLS]\n"
    "- \"args\" keys MUST match the arguments listed for that tool\n"
    "- NEVER hallucinate tools or parameters\n"
    "- Use safe Windows paths; default home directory: {home}\n"
    "\n"
    "[SAFETY]\n"
    "- For destructive actions (delete_item): only include if user explicitly asked\n"
    "- If the command is ambiguous or missing details, use talk_back to ask for clarification\n"
    "\n"
    "[FORMAT]\n"
    "[\n"
    "  {{\n"
    "    \"tool\": \"<tool_name>\",\n"
    "    \"args\": {{ \"<param>\": \"<value>\" }}\n"
    "  }}\n"
    "]\n"
    "\n"
    "[INPUT]\n"
    "User Command: {command}\n"
    "\n"
    "[OUTPUT]\n"
)

# ── Arg order for positional dispatch ────────────────────────────────────────

_ARG_ORDER = {
    "sort_directory":  ["path", "criteria"],
    "create_folder":   ["path"],
    "delete_item":     ["path"],
    "install_app":     ["app_name"],
    "open_vscode":     ["filepath"],
    "focus_editor":    [],
    "type_code":       ["text"],
    "create_file":     [],
    "save_file":       [],
    "toggle_terminal": [],
    "open_and_type":   ["text", "save"],
    "upgrade_yourself":["target_path", "code_snippet"],
}

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# Tracks the error type from the most recent _call_llm() invocation.
_last_api_error: str | None = None


def _classify_api_error(e: Exception) -> str:
    err  = str(e).lower()
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    if code == 429 or "429" in err or "quota" in err or ("rate" in err and "limit" in err):
        return "API_QUOTA"
    if isinstance(e, (ConnectionError, TimeoutError)) or "connection" in err or "timeout" in err:
        return "CONNECTION"
    return "CONNECTION"


def _extract_json(raw: str) -> str:
    m = _JSON_FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()
    start = raw.find("[")
    end   = raw.rfind("]")
    if start != -1 and end != -1:
        return raw[start:end + 1]
    return raw.strip()


def _parse_steps(llm_output: str) -> list[dict]:
    """Return list of validated {tool, args} dicts."""
    cleaned = _extract_json(llm_output)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[Director] JSON parse error: {e}\nRaw output:\n{llm_output[:400]}")
        return []

    if not isinstance(data, list):
        print("[Director] LLM output is not a JSON array.")
        return []

    steps: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool", "").strip()
        args = item.get("args", {})
        if tool not in _ALLOWED_TOOLS:
            print(f"[Director] Blocked unknown tool: {tool!r} (not in knowledge_base)")
            continue
        if not isinstance(args, dict):
            args = {}
        steps.append({"tool": tool, "args": args})
    return steps


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
    return libs[:3]


def _call_llm(prompt: str) -> str:
    global _last_api_error
    _last_api_error = None

    # Priority 1: llama_cpp (local — no quota issues)
    try:
        from llama_cpp import Llama
        model_path = os.getenv("LOCAL_MODEL_PATH", os.path.join("models", "llama.gguf"))
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
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
    except (ConnectionError, TimeoutError) as e:
        _last_api_error = "CONNECTION"
        print(f"[Orchestrator] Anthropic connection error: {e}", file=sys.stderr)
    except Exception as e:
        _last_api_error = _classify_api_error(e)
        print(f"[Orchestrator] Anthropic error ({_last_api_error}): {e}", file=sys.stderr)

    # Priority 3: Gemini Flash (Director default)
    try:
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            return response.text.strip()
    except (ConnectionError, TimeoutError) as e:
        _last_api_error = "CONNECTION"
        print(f"[Orchestrator] Gemini connection error: {e}", file=sys.stderr)
    except Exception as e:
        _last_api_error = _classify_api_error(e)
        print(f"[Orchestrator] Gemini error ({_last_api_error}): {e}", file=sys.stderr)

    return ""


def _build_prompt(intent_label: str, code: str, docs: str) -> str:
    instruction = INTENT_INSTRUCTIONS.get(intent_label, INTENT_INSTRUCTIONS["DEV_EXPLAIN"])
    parts = [instruction, "\n\n--- CODE ---\n", code]
    if docs:
        parts += ["\n\n--- RELEVANT DOCUMENTATION ---\n", docs]
    return "".join(parts)


class Orchestrator:

    def run_dev_loop(self, intent_label: str) -> None:
        _speak("Reading clipboard...")
        print("[Orchestrator] Reading clipboard...")
        code = get_code_context()

        if not code:
            print("[Orchestrator] Clipboard is empty or contains no code.")
            _speak("Clipboard is empty.")
            return

        docs = ""
        libs = _extract_libraries(code)
        if libs:
            _speak("Searching documentation...")
            print(f"[Orchestrator] Fetching docs for: {libs}")
            doc_parts = []
            for lib in libs:
                try:
                    result = fetch_docs(lib)
                    if result:
                        doc_parts.append(f"[{lib}]\n{result}")
                except (ConnectionError, TimeoutError) as e:
                    print(f"[Orchestrator] Doc fetch connection error for {lib}: {e}", file=sys.stderr)
                    _speak("API quota exceeded. Falling back to local keyword engine.")
                except Exception as e:
                    print(f"[Orchestrator] Doc fetch error for {lib}: {e}", file=sys.stderr)
            docs = "\n\n".join(doc_parts)

        prompt = _build_prompt(intent_label, code, docs)

        _speak("Consulting AI model...")
        print("[Orchestrator] Sending to LLM...")
        llm_response = _call_llm(prompt)

        if not llm_response:
            error_type = _last_api_error or "CONNECTION"
            print(f"[Orchestrator] LLM returned no response. Error type: {error_type}")
            _speak("API quota exceeded. Falling back to local keyword engine.")
            return

        set_clipboard_text(llm_response)
        print(f"[Orchestrator] Result copied to clipboard ({len(llm_response)} chars).")

        completion_msg = COMPLETION_MESSAGES.get(intent_label, "Task complete")
        _speak(completion_msg)
        print(f"[Orchestrator] {completion_msg}.")

    def run_director_loop(self, command_text: str, synth=None) -> list[str]:
        def _say(text: str):
            if synth:
                synth.speak(text)
            else:
                _speak(text)

        def _set_state(status: str, action: str = "—"):
            try:
                from core.dashboard import set_exec_state
                set_exec_state(status, action)
            except Exception:
                pass

        _set_state("RUNNING", f"Planning: {command_text[:50]}")
        _say("Let me work on that.")
        print(f"[Director] Command: {command_text}")

        prompt = DIRECTOR_PROMPT.format(command=command_text, home=_HOME)
        print("[Director] Consulting LLM for JSON action plan...")
        raw = _call_llm(prompt)

        if not raw:
            error_type = _last_api_error or "CONNECTION"
            _set_state("FAILED", f"{error_type}: LLM unavailable")
            _say("API quota exceeded. Falling back to local keyword engine.")
            print(f"[Director] LLM unavailable. Error type: {error_type}")
            return []

        print(f"[Director] Raw LLM response:\n{raw[:600]}")
        steps = _parse_steps(raw)

        if not steps:
            _set_state("FAILED", "No valid steps parsed")
            _say("I couldn't parse a valid action plan.")
            return []

        print(f"[Director] Action plan ({len(steps)} step(s)):")
        for i, s in enumerate(steps, 1):
            print(f"  {i}. {s['tool']} {s['args']}")

        agent = OSAgent()
        executed: list[str] = []

        method_map = {
            "sort_directory":  agent.sort_directory,
            "create_folder":   agent.create_folder,
            "delete_item":     agent.delete_item,
            "install_app":     agent.install_app,
            "open_vscode":     agent.open_vscode,
            "focus_editor":    agent.focus_editor,
            "type_code":       agent.type_code,
        }

        for step in steps:
            tool = step["tool"]
            args = step["args"]
            step_label = f"{tool}({args})"

            if tool == "talk_back":
                msg = args.get("message", "Can you clarify your request?")
                _say(msg)
                print(f"[Director] talk_back: {msg}")
                _set_state("IDLE", "Awaiting clarification")
                return []

            _set_state("RUNNING", step_label)
            print(f"[Director] Executing: {step_label}")

            method = method_map.get(tool)
            if method is None:
                print(f"[Director] No dispatch method for tool: {tool!r}", file=sys.stderr)
                continue

            arg_order = _ARG_ORDER.get(tool, [])
            positional = [args[k] for k in arg_order if k in args]
            extra_kwargs = {k: v for k, v in args.items() if k not in arg_order}

            try:
                method(*positional, **extra_kwargs)
                executed.append(step_label)
            except TypeError as e:
                print(f"[Director] Bad args for {tool}: {e}", file=sys.stderr)
                _set_state("FAILED", step_label)
            except Exception as e:
                print(f"[Director] Step failed — {tool}: {e}", file=sys.stderr)
                _set_state("FAILED", step_label)

        if executed:
            _set_state("SUCCESS", f"Done: {len(executed)} step(s)")
            _say(f"Done. Completed {len(executed)} action{'s' if len(executed) != 1 else ''}.")
        else:
            _set_state("FAILED", "All steps failed")
            _say("All steps failed. Check the console for details.")

        return executed
