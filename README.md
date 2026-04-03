# VoiceTyper 🎙️

**Linux desktop speech-to-text tool** – beszélj, és a szöveg oda kerül, ahol a kurzor áll.

> Press **Ctrl + ↓** to start recording, press again to stop.  
> The transcribed text is "typed" into whatever application has focus.

## Features

- 🎤 **Global hotkey** (Ctrl+Down) – works from any application
- 🧠 **OpenAI Whisper** – offline, GPU-accelerated speech recognition
- 🇬🇧🇭🇺 **English & Hungarian** – auto-detected per recording
- ⌨️ **Types into any app** – Claude chat, browser, editor, anything
- 🔴 **Visual indicator** – small overlay shows recording status
- 🚀 **Fast** – medium model transcribes 10s of audio in ~1-2s on GPU

## How it works

```
┌──────────────────────────────────────────────────────┐
│  1. Ctrl+↓  →  Start recording (microphone)          │
│  2. Ctrl+↓  →  Stop recording                        │
│  3. Whisper →  Transcribe audio (GPU)                 │
│  4. xdotool →  Type text into focused window          │
│  5. You     →  Press Enter to send                    │
└──────────────────────────────────────────────────────┘
```

## Installation

```bash
# Clone or copy the project
cd voice-typer

# Run the installer (handles everything)
chmod +x install.sh
./install.sh
```

The installer will:
- Check and install system dependencies (xdotool, ffmpeg, portaudio, etc.)
- Create a Python virtual environment
- Install PyTorch with CUDA support (if GPU detected)
- Install OpenAI Whisper
- Download the recommended model for your GPU
- Create a desktop launcher and optional autostart entry

## Usage

```bash
# Start VoiceTyper
./start.sh

# Or with a specific model
VOICE_TYPER_MODEL=large-v3 ./start.sh
```

### Workflow
1. Start VoiceTyper (a small indicator appears in the bottom-right corner)
2. Click into Claude chat (or any text field)
3. Press **Ctrl + ↓** → indicator turns red (recording)
4. Speak in English or Hungarian
5. Press **Ctrl + ↓** → indicator turns yellow (transcribing)
6. Text appears in the text field as if you typed it
7. Press **Enter** to send

### Models

| Model     | VRAM   | Speed    | Quality    |
|-----------|--------|----------|------------|
| `base`    | ~1 GB  | Fastest  | OK         |
| `small`   | ~2 GB  | Fast     | Good       |
| `medium`  | ~5 GB  | Balanced | Very Good  |
| `large-v3`| ~10 GB | Slower   | Best       |

## Using with Claude Code

You can ask Claude Code to extend this project:

```bash
# Open the project with Claude Code
cd voice-typer
claude

# Example prompts:
# "Add a config file for custom hotkeys"
# "Add support for Wayland (wtype instead of xdotool)"
# "Add a system tray icon with PyGObject"
# "Add voice activity detection to auto-stop recording"
# "Add a language selection menu"
# "Replace Whisper with faster-whisper for better performance"
```

### Suggested improvements for Claude Code:
1. **faster-whisper** – CTranslate2-based, 4x faster than vanilla Whisper
2. **Wayland support** – use `wtype` or `ydotool` instead of `xdotool`
3. **System tray** – proper GTK/AppIndicator tray icon
4. **Voice Activity Detection** – auto-stop when silence detected
5. **Custom hotkeys** – configurable via config file
6. **Clipboard mode** – paste instead of type (for long texts)

## Troubleshooting

### No audio recorded
```bash
# Check your microphone
arecord -l                    # List recording devices
pavucontrol                   # PulseAudio volume control
```

### xdotool not typing
- Make sure you're on X11 (not pure Wayland)
- For Wayland: use XWayland apps, or ask Claude Code to add wtype support

### Slow transcription
- Use a smaller model: `VOICE_TYPER_MODEL=base ./start.sh`
- Check GPU is being used: `nvidia-smi` during transcription

### Hungarian characters not appearing
- xdotool should handle UTF-8 natively
- If issues persist, the app falls back to clipboard paste (xclip)

## Requirements

- Linux (Ubuntu 20.04+ recommended)
- Python 3.10+
- X11 (or XWayland)
- NVIDIA GPU recommended (works on CPU too, just slower)
- Microphone

## License

MIT – do whatever you want with it.
