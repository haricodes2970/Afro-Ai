import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

load_dotenv()

VALID_LABELS = {"FILE_OPS", "PROCESS_OPS", "CALENDAR_OPS", "SYSTEM_QUERY", "UNKNOWN"}

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
            return label

        except Exception as e:
            print(f"[IntentRouter error] {e}", file=sys.stderr)
            return "UNKNOWN"
