#!/usr/bin/env python3
"""
Voice Typer - Linux desktop speech-to-text tool
================================================
Ctrl+Down: Start/stop recording
The transcribed text is typed into whatever window has focus.

Requires: Python 3.10+, PulseAudio/PipeWire, X11 or XWayland
GPU-accelerated via OpenAI Whisper (large-v3 model)
Supports: English & Hungarian
"""

import sys
import os
import signal
import threading
import tempfile
import subprocess
import time
import queue
from pathlib import Path

# --- Dependency checks ---
def check_dependencies():
    missing = []
    try:
        import whisper  # noqa: F401
    except ImportError:
        missing.append("openai-whisper")
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        missing.append("sounddevice")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    try:
        import scipy  # noqa: F401
    except ImportError:
        missing.append("scipy")
    try:
        from pynput import keyboard  # noqa: F401
    except ImportError:
        missing.append("pynput")

    if missing:
        print("Missing dependencies. Install with:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)

    # Check xdotool
    if subprocess.run(["which", "xdotool"], capture_output=True).returncode != 0:
        print("Missing xdotool. Install with:")
        print("  sudo apt install xdotool")
        sys.exit(1)


check_dependencies()

import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from pynput import keyboard
import whisper

# ─── Configuration ───────────────────────────────────────────────────────────

SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 1
WHISPER_MODEL = os.environ.get("VOICE_TYPER_MODEL", "medium")
# "medium" is a good balance; use "large-v3" for best quality (needs ~10GB VRAM)
# Use "small" or "base" for faster/lower VRAM

HOTKEY = {keyboard.Key.ctrl_l, keyboard.Key.down}
# Also accept right ctrl
HOTKEY_ALT = {keyboard.Key.ctrl_r, keyboard.Key.down}

TYPING_DELAY = 0.01  # seconds between characters when typing via xdotool


# ─── Tray / Notification helpers ────────────────────────────────────────────

def notify(title: str, message: str, urgency: str = "normal"):
    """Send a desktop notification."""
    try:
        subprocess.Popen(
            ["notify-send", f"--urgency={urgency}", "--app-name=VoiceTyper",
             "--icon=audio-input-microphone", title, message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        pass  # notify-send not available


def set_tray_icon(recording: bool):
    """
    We use a simple approach: a small always-on-top, non-focusable window
    via tkinter that shows the current state. This avoids heavy dependencies
    like PyGObject for system tray.
    """
    # Handled by the TrayWindow class below
    pass


# ─── Tray Window (tiny status indicator) ────────────────────────────────────

class TrayWindow:
    """
    A tiny always-on-top, non-focusable tkinter window that sits in the
    corner of the screen showing recording status.
    """

    def __init__(self):
        import tkinter as tk

        self.root = tk.Tk()
        self.root.title("VoiceTyper")
        self.root.overrideredirect(True)  # No window decorations
        self.root.attributes("-topmost", True)  # Always on top
        self.root.attributes("-alpha", 0.85)

        # Position: bottom-right corner
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w, win_h = 180, 40
        x = screen_w - win_w - 20
        y = screen_h - win_h - 60
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")

        self.label = tk.Label(
            self.root,
            text="🎙️ VoiceTyper: Ready",
            font=("Sans", 10),
            bg="#2d2d2d",
            fg="#88cc88",
            padx=8, pady=6
        )
        self.label.pack(fill=tk.BOTH, expand=True)
        self.root.configure(bg="#2d2d2d")

        # Make it not steal focus (X11)
        try:
            self.root.after(100, self._set_skip_taskbar)
        except Exception:
            pass

        self._update_queue = queue.Queue()
        self._poll_updates()

    def _set_skip_taskbar(self):
        """Use wmctrl or xdotool to make the window skip the taskbar."""
        try:
            wid = self.root.winfo_id()
            subprocess.Popen(
                ["xdotool", "set_window", "--overrideredirect", "1", str(wid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    def _poll_updates(self):
        """Poll for thread-safe UI updates."""
        try:
            while True:
                text, color = self._update_queue.get_nowait()
                self.label.config(text=text, fg=color)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_updates)

    def set_state(self, state: str):
        """Thread-safe state update."""
        states = {
            "ready":        ("🎙️ VoiceTyper: Ready",      "#88cc88"),
            "recording":    ("🔴 Recording...",             "#ff4444"),
            "transcribing": ("⏳ Transcribing...",          "#ffaa44"),
            "typing":       ("⌨️  Typing...",               "#4488ff"),
            "error":        ("❌ Error",                    "#ff4444"),
        }
        text, color = states.get(state, states["ready"])
        self._update_queue.put((text, color))

    def run(self):
        """Start the tkinter main loop (blocking)."""
        self.root.mainloop()

    def quit(self):
        self.root.quit()


# ─── Audio Recorder ─────────────────────────────────────────────────────────

class AudioRecorder:
    def __init__(self):
        self.frames: list[np.ndarray] = []
        self.is_recording = False
        self.stream = None

    def start(self):
        self.frames = []
        self.is_recording = True
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._audio_callback,
        )
        self.stream.start()

    def _audio_callback(self, indata, frames, time_info, status):
        if self.is_recording:
            self.frames.append(indata.copy())

    def stop(self) -> str | None:
        """Stop recording, save to temp WAV, return path."""
        self.is_recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if not self.frames:
            return None

        audio = np.concatenate(self.frames, axis=0)

        # Skip very short recordings (< 0.3 sec)
        if len(audio) < SAMPLE_RATE * 0.3:
            return None

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        # scipy expects int16
        audio_int16 = (audio * 32767).astype(np.int16)
        wavfile.write(tmp.name, SAMPLE_RATE, audio_int16)
        return tmp.name


# ─── Whisper Transcriber ────────────────────────────────────────────────────

class Transcriber:
    def __init__(self, model_name: str = WHISPER_MODEL):
        print(f"Loading Whisper model '{model_name}' (this may take a moment)...")
        notify("VoiceTyper", f"Loading Whisper model '{model_name}'...")
        self.model = whisper.load_model(model_name)
        device = "GPU" if next(self.model.parameters()).is_cuda else "CPU"
        print(f"Model loaded on {device}.")
        notify("VoiceTyper", f"Ready! Model on {device}. Press Ctrl+↓ to record.")

    def transcribe(self, audio_path: str) -> str:
        """Transcribe audio file. Auto-detects English/Hungarian."""
        result = self.model.transcribe(
            audio_path,
            language=None,  # Auto-detect
            task="transcribe",
            fp16=True,  # Use FP16 on GPU
        )
        text = result.get("text", "").strip()
        lang = result.get("language", "unknown")
        print(f"  Detected language: {lang}")
        print(f"  Text: {text}")
        return text


# ─── Text Typer (xdotool) ──────────────────────────────────────────────────

def type_text(text: str):
    """
    Type text into the currently focused window using xdotool.
    Uses xdotool type with --clearmodifiers to handle special characters.
    For Hungarian characters, we use xdotool's built-in Unicode support.
    """
    if not text:
        return

    # xdotool type handles Unicode well on X11
    # --clearmodifiers releases any held keys (like Ctrl from our hotkey)
    # --delay controls typing speed in ms
    try:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers",
             "--delay", str(int(TYPING_DELAY * 1000)), text],
            check=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        print("Warning: xdotool typing timed out")
    except subprocess.CalledProcessError as e:
        print(f"Warning: xdotool error: {e}")
        # Fallback: clipboard paste
        _paste_text(text)


def _paste_text(text: str):
    """Fallback: copy to clipboard and paste with Ctrl+V."""
    try:
        proc = subprocess.Popen(
            ["xclip", "-selection", "clipboard"],
            stdin=subprocess.PIPE
        )
        proc.communicate(text.encode("utf-8"))
        time.sleep(0.1)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                       check=True)
    except Exception as e:
        print(f"Paste fallback also failed: {e}")


# ─── Main Application ───────────────────────────────────────────────────────

class VoiceTyperApp:
    def __init__(self):
        self.recorder = AudioRecorder()
        self.transcriber = None  # Lazy load
        self.tray: TrayWindow | None = None
        self.is_recording = False
        self.current_keys = set()
        self._loading_model = False

    def _ensure_model(self):
        if self.transcriber is None and not self._loading_model:
            self._loading_model = True
            self.transcriber = Transcriber()
            self._loading_model = False

    def toggle_recording(self):
        if self.is_recording:
            self._stop_and_transcribe()
        else:
            self._start_recording()

    def _start_recording(self):
        self.is_recording = True
        self.recorder.start()
        print("🔴 Recording started...")
        notify("VoiceTyper", "Recording... Press Ctrl+↓ to stop.", "low")
        if self.tray:
            self.tray.set_state("recording")

    def _stop_and_transcribe(self):
        self.is_recording = False
        print("⏹️  Recording stopped. Transcribing...")
        if self.tray:
            self.tray.set_state("transcribing")

        audio_path = self.recorder.stop()
        if audio_path is None:
            print("  Recording too short, skipping.")
            notify("VoiceTyper", "Recording too short.", "low")
            if self.tray:
                self.tray.set_state("ready")
            return

        # Transcribe in a thread to not block hotkey listener
        def _do_transcribe():
            try:
                self._ensure_model()
                text = self.transcriber.transcribe(audio_path)

                # Clean up temp file
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

                if text:
                    print(f"⌨️  Typing: {text}")
                    if self.tray:
                        self.tray.set_state("typing")
                    # Small delay to ensure Ctrl key is released
                    time.sleep(0.2)
                    type_text(text)
                    notify("VoiceTyper", f"Typed: {text[:60]}...", "low")
                else:
                    print("  No speech detected.")
                    notify("VoiceTyper", "No speech detected.", "low")

            except Exception as e:
                print(f"  Transcription error: {e}")
                notify("VoiceTyper", f"Error: {e}", "critical")
                if self.tray:
                    self.tray.set_state("error")
                time.sleep(2)
            finally:
                if self.tray:
                    self.tray.set_state("ready")

        threading.Thread(target=_do_transcribe, daemon=True).start()

    def _on_press(self, key):
        self.current_keys.add(key)
        if self.current_keys >= HOTKEY or self.current_keys >= HOTKEY_ALT:
            self.toggle_recording()
            # Reset to avoid repeated triggers
            self.current_keys.clear()

    def _on_release(self, key):
        self.current_keys.discard(key)

    def run(self):
        print("=" * 50)
        print("  VoiceTyper - Speech to Text for Linux")
        print("=" * 50)
        print(f"  Model: {WHISPER_MODEL}")
        print("  Hotkey: Ctrl + ↓ (Down Arrow)")
        print("  Languages: English, Hungarian (auto-detect)")
        print("=" * 50)
        print()

        # Pre-load model in background
        model_thread = threading.Thread(target=self._ensure_model, daemon=True)
        model_thread.start()

        # Start global hotkey listener
        listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        listener.daemon = True
        listener.start()

        print("Listening for hotkeys... (Ctrl+C to quit)")

        # Start tray window (runs tkinter mainloop)
        try:
            self.tray = TrayWindow()
            # Handle Ctrl+C gracefully
            signal.signal(signal.SIGINT, lambda *_: self.tray.quit())
            self.tray.run()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Tray window error: {e}")
            print("Running without tray (headless mode)...")
            # Fallback: just wait
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        print("\nGoodbye!")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = VoiceTyperApp()
    app.run()
