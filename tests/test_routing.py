import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestIntentRouter(unittest.TestCase):

    def _make_router(self, llm_response: str):
        """Return IntentRouter with mocked LLM returning llm_response."""
        with patch("core.intent_router.ChatOpenAI") as MockLLM:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = MagicMock(content=llm_response)
            MockLLM.return_value = mock_instance

            from core.intent_router import IntentRouter
            router = IntentRouter()
            router._llm = mock_instance
            return router

    def test_file_ops_delete_downloads(self):
        router = self._make_router("FILE_OPS")
        result = router.route("Delete my downloads")
        self.assertEqual(result, "FILE_OPS")

    def test_process_ops_kill_chrome(self):
        router = self._make_router("PROCESS_OPS")
        result = router.route("Kill chrome")
        self.assertEqual(result, "PROCESS_OPS")

    def test_calendar_ops(self):
        router = self._make_router("CALENDAR_OPS")
        result = router.route("Schedule a meeting for tomorrow at 3pm")
        self.assertEqual(result, "CALENDAR_OPS")

    def test_system_query(self):
        router = self._make_router("SYSTEM_QUERY")
        result = router.route("What is my CPU usage?")
        self.assertEqual(result, "SYSTEM_QUERY")

    def test_unknown_label(self):
        router = self._make_router("UNKNOWN")
        result = router.route("Tell me a joke")
        self.assertEqual(result, "UNKNOWN")

    def test_invalid_llm_response_falls_back_to_unknown(self):
        router = self._make_router("SOME_GARBAGE_LABEL")
        result = router.route("Do something weird")
        self.assertEqual(result, "UNKNOWN")

    def test_empty_input_returns_unknown(self):
        router = self._make_router("FILE_OPS")
        result = router.route("")
        self.assertEqual(result, "UNKNOWN")

    def test_whitespace_input_returns_unknown(self):
        router = self._make_router("FILE_OPS")
        result = router.route("   ")
        self.assertEqual(result, "UNKNOWN")

    def test_llm_exception_returns_unknown(self):
        with patch("core.intent_router.ChatOpenAI") as MockLLM:
            mock_instance = MagicMock()
            mock_instance.invoke.side_effect = RuntimeError("API down")
            MockLLM.return_value = mock_instance

            from core.intent_router import IntentRouter
            router = IntentRouter()
            router._llm = mock_instance
            result = router.route("Sort my files")
            self.assertEqual(result, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
