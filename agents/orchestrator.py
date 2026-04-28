import ast
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

DIRECTOR_PROMPT = (
    "Convert this voice command into a list of Python-style function calls.\n"
    "Use ONLY these allowed functions:\n"
    "  sort_directory(path, criteria)\n"
    "  create_folder(path)\n"
    "  delete_item(path)\n"
    "  install_app(app_name)\n"
    "  open_vscode(filepath='')\n"
    "  type_code(text)\n\n"
    "Rules:\n"
    "- Return ONLY function calls, one per line\n"
    "- Use real paths when mentioned, default to common Windows paths otherwise\n"
    "- NO explanations, NO import statements, NO markdown\n\n"
    "Command: {command}\n"
    "Function calls:"
)

# Safe dispatcher: maps function names → OSAgent method calls
_ALLOWED_CALLS = {
    "sort_directory",
    "create_folder",
    "delete_item",
    "install_app",
    "open_vscode",
    "type_code",
}

_STEP_RE = re.compile(r"^(\w+)\((.*)\)$", re.DOTALL)


def _parse_steps(llm_output: str) -> list[tuple[str, list]]:
    steps = []
    for raw_line in llm_output.splitlines():
        line = raw_line.strip().strip("`").strip()
        if not line or line.startswith("#"):
            continue
        m = _STEP_RE.match(line)
        if not m:
            continue
        fn_name = m.group(1)
        if fn_name not in _ALLOWED_CALLS:
            print(f"[Orchestrator] Blocked disallowed call: {fn_name}")
            continue
        raw_args = m.group(2).strip()
        try:
            args = list(ast.literal_eval(f"({raw_args},)")) if raw_args else []
        except Exception:
            # Try wrapping bare string
            try:
                args = [ast.literal_eval(raw_args)]
            except Exception:
                args = [raw_args] if raw_args else []
        steps.append((fn_name, args))
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
    # Priority 1: llama_cpp
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
    except Exception:
        pass

    # Priority 3: Gemini Flash (Director default)
    try:
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
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
                result = fetch_docs(lib)
                if result:
                    doc_parts.append(f"[{lib}]\n{result}")
            docs = "\n\n".join(doc_parts)

        prompt = _build_prompt(intent_label, code, docs)

        _speak("Consulting AI model...")
        print("[Orchestrator] Sending to LLM...")
        llm_response = _call_llm(prompt)

        if not llm_response:
            print("[Orchestrator] LLM returned no response.")
            _speak("No response from AI model.")
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

        # Build director prompt and call Gemini Flash
        prompt = DIRECTOR_PROMPT.format(command=command_text)
        print("[Director] Consulting Gemini Flash for action plan...")
        raw = _call_llm(prompt)

        if not raw:
            _set_state("FAILED", "LLM unavailable")
            _say("I couldn't generate a plan. LLM is unavailable.")
            return []

        steps = _parse_steps(raw)
        if not steps:
            _set_state("FAILED", "No valid steps parsed")
            print(f"[Director] Could not parse steps from:\n{raw}")
            _say("I couldn't parse a valid action plan.")
            return []

        print(f"[Director] Action plan ({len(steps)} step(s)):")
        for i, (fn, args) in enumerate(steps, 1):
            print(f"  {i}. {fn}({', '.join(repr(a) for a in args)})")

        agent = OSAgent()
        executed: list[str] = []
        method_map = {
            "sort_directory": agent.sort_directory,
            "create_folder":  agent.create_folder,
            "delete_item":    agent.delete_item,
            "install_app":    agent.install_app,
            "open_vscode":    agent.open_vscode,
            "type_code":      agent.type_code,
        }

        for fn_name, args in steps:
            step_label = f"{fn_name}({', '.join(repr(a) for a in args)})"
            _set_state("RUNNING", step_label)
            print(f"[Director] Executing: {step_label}")

            try:
                method = method_map[fn_name]
                method(*args)
                executed.append(step_label)
            except TypeError as e:
                print(f"[Director] Bad args for {fn_name}: {e}", file=sys.stderr)
                _set_state("FAILED", step_label)
                continue
            except Exception as e:
                print(f"[Director] Step failed — {fn_name}: {e}", file=sys.stderr)
                _set_state("FAILED", step_label)
                continue

        if executed:
            _set_state("SUCCESS", f"Done: {len(executed)} step(s)")
            _say(f"Done. Completed {len(executed)} action{'s' if len(executed) != 1 else ''}.")
        else:
            _set_state("FAILED", "All steps failed")
            _say("All steps failed. Check the console for details.")

        return executed
