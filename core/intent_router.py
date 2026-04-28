import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

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

SYSTEM_PROMPT = """You are an intent classifier. Classify the user's input into exactly one of these labels:

FILE_OPS
PROCESS_OPS
CALENDAR_OPS
SYSTEM_QUERY
UNKNOWN

Rules:
- Respond with ONLY the label. No punctuation. No explanation.
- FILE_OPS: file creation, deletion, sorting, moving, renaming, downloads, documents
- PROCESS_OPS: killing, stopping, launching, managing processes or applications
- CALENDAR_OPS: scheduling, meetings, reminders, events, dates, times
- SYSTEM_QUERY: system info, CPU, RAM, battery, network, status queries
- UNKNOWN: anything else"""


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
        confirmed = confirm_action(f"Rename files in: {target_directory}")
        if not confirmed:
            print("Operation aborted by user")
            return
        agent.rename(target_directory)

    elif operation_type == "DELETE":
        confirmed = confirm_action(f"Delete files in: {target_directory}")
        if not confirmed:
            print("Operation aborted by user")
            return
        print(f"[FileAgent] DELETE requested for: {target_directory}")
        print("[FileAgent] Specify exact file_path for deletion.")


class IntentRouter:
    def __init__(self):
        self._llm = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0,
        )

    def route(self, transcribed_text: str) -> str:
        if not transcribed_text or not transcribed_text.strip():
            return "UNKNOWN"

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=transcribed_text.strip()),
            ]
            response = self._llm.invoke(messages)
            label = response.content.strip().upper()

            if label not in VALID_LABELS:
                return "UNKNOWN"

            if label == "FILE_OPS":
                _dispatch_file_ops(transcribed_text)

            return label

        except Exception as e:
            print(f"[IntentRouter error] {e}", file=sys.stderr)
            return "UNKNOWN"
