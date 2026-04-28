import sys


def _gui_confirm(action_description: str) -> bool:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        result = messagebox.askyesno(
            title="Afro Safety Gate",
            message=f"Are you sure you want to proceed with:\n\n{action_description}?",
        )
        root.destroy()
        return bool(result)
    except Exception as e:
        print(f"[Safety] GUI unavailable: {e}")
        return None


def _voice_confirm() -> bool:
    try:
        import pyttsx3
        import speech_recognition as sr

        engine = pyttsx3.init()
        engine.say("Please confirm. Say yes to proceed or no to cancel.")
        engine.runAndWait()

        recognizer = sr.Recognizer()
        mic = sr.Microphone()

        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            print("[Safety] Waiting for voice confirmation...")
            audio = recognizer.listen(source, timeout=7, phrase_time_limit=5)

        text = recognizer.recognize_google(audio).strip().lower()
        print(f"[Safety] Voice input: '{text}'")
        return "yes" in text

    except Exception as e:
        print(f"[Safety] Voice confirmation failed: {e}")
        return None


def _console_confirm(action_description: str) -> bool:
    try:
        answer = input(
            f"[Safety] Confirm: '{action_description}' — type yes/no: "
        ).strip().lower()
        return answer == "yes"
    except (EOFError, KeyboardInterrupt):
        return False


def confirm_action(action_description: str) -> bool:
    print(f"[Safety] Gate triggered for: {action_description}")

    gui_result = _gui_confirm(action_description)
    if gui_result is False:
        print("[Safety] Denied via GUI.")
        return False

    voice_result = _voice_confirm()
    if voice_result is not None:
        if not voice_result:
            print("[Safety] Denied via voice.")
            return False
        print("[Safety] Confirmed via voice.")
        return True

    console_result = _console_confirm(action_description)
    if not console_result:
        print("[Safety] Denied via console.")
        return False

    print("[Safety] Confirmed via console.")
    return True
