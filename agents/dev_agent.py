import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.clipboard import get_text, set_text
from core.llm_factory import LLMFactory

_factory = LLMFactory()

PROMPTS = {
    "DEV_OPTIMIZE": (
        "Optimize the following code for performance, readability, and security. "
        "Return ONLY the improved code with no explanation or markdown."
    ),
    "DEV_EXPLAIN": (
        "Explain this code in simple terms. "
        "Describe what it does, how it works, and any notable patterns or concerns."
    ),
    "DEV_DEBUG": (
        "Fix all bugs in the following code and explain each fix at the end. "
        "Return the corrected code first, then a short bullet list of changes."
    ),
}


class DevAgent:

    def _run(self, intent_label: str) -> str:
        code = get_text()
        if not code:
            print("[DevAgent] Clipboard is empty.")
            return ""

        system_prompt = PROMPTS.get(intent_label, PROMPTS["DEV_EXPLAIN"])
        response = _factory.call(intent_label, system_prompt, code)

        if response:
            set_text(response)
            print(f"[DevAgent] Result copied to clipboard ({len(response)} chars).")
        else:
            print("[DevAgent] No response from LLM.")

        return response

    def optimize_code(self) -> str:
        return self._run("DEV_OPTIMIZE")

    def explain_code(self) -> str:
        return self._run("DEV_EXPLAIN")

    def debug_code(self) -> str:
        return self._run("DEV_DEBUG")
