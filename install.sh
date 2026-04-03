#!/bin/bash
# ============================================================================
#  VoiceTyper - Installation Script
#  Linux desktop speech-to-text with global hotkey
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════════════╗"
echo "║        VoiceTyper - Installation                 ║"
echo "╚══════════════════════════════════════════════════╝"
echo

# --- Check Python ---
echo "▸ Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo "  ✗ Python 3 not found. Install with: sudo apt install python3"
    exit 1
fi

PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  ✓ Python $PYTHON_VER"

# --- Check system dependencies ---
echo
echo "▸ Checking system dependencies..."

NEED_APT=()

if ! command -v xdotool &>/dev/null; then
    NEED_APT+=("xdotool")
fi
if ! command -v xclip &>/dev/null; then
    NEED_APT+=("xclip")
fi
if ! command -v notify-send &>/dev/null; then
    NEED_APT+=("libnotify-bin")
fi
if ! dpkg -l | grep -q "portaudio19-dev\|libportaudio2" 2>/dev/null; then
    NEED_APT+=("portaudio19-dev")
fi
if ! command -v ffmpeg &>/dev/null; then
    NEED_APT+=("ffmpeg")
fi
# tkinter
if ! python3 -c "import tkinter" 2>/dev/null; then
    NEED_APT+=("python3-tk")
fi

if [ ${#NEED_APT[@]} -gt 0 ]; then
    echo "  Installing: ${NEED_APT[*]}"
    sudo apt update -qq
    sudo apt install -y "${NEED_APT[@]}"
else
    echo "  ✓ All system dependencies installed"
fi

# --- Check GPU ---
echo
echo "▸ Checking GPU..."
if command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    echo "  ✓ GPU: $GPU_NAME (${GPU_MEM}MB VRAM)"

    if [ "$GPU_MEM" -ge 10000 ] 2>/dev/null; then
        RECOMMENDED_MODEL="large-v3"
        echo "  → Recommended model: large-v3 (best quality)"
    elif [ "$GPU_MEM" -ge 5000 ] 2>/dev/null; then
        RECOMMENDED_MODEL="medium"
        echo "  → Recommended model: medium (good balance)"
    else
        RECOMMENDED_MODEL="small"
        echo "  → Recommended model: small (limited VRAM)"
    fi
else
    echo "  ⚠ No NVIDIA GPU detected (will use CPU - slower)"
    RECOMMENDED_MODEL="base"
fi

# --- Create virtual environment ---
echo
echo "▸ Setting up Python virtual environment..."

VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "  ✓ Created venv"
else
    echo "  ✓ venv already exists"
fi

source "$VENV_DIR/bin/activate"

# --- Install Python packages ---
echo
echo "▸ Installing Python packages..."

pip install --upgrade pip -q

# Install PyTorch with CUDA if GPU available
if command -v nvidia-smi &>/dev/null; then
    echo "  Installing PyTorch with CUDA support..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 -q
else
    echo "  Installing PyTorch (CPU)..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu -q
fi

echo "  Installing Whisper and other dependencies..."
pip install openai-whisper sounddevice numpy scipy pynput -q

echo "  ✓ All Python packages installed"

# --- Download Whisper model ---
echo
echo "▸ Pre-downloading Whisper model ($RECOMMENDED_MODEL)..."
python3 -c "import whisper; whisper.load_model('$RECOMMENDED_MODEL')"
echo "  ✓ Model downloaded"

# --- Create launcher script ---
echo
echo "▸ Creating launcher script..."

cat > "$SCRIPT_DIR/start.sh" << LAUNCHER
#!/bin/bash
# VoiceTyper launcher
cd "$SCRIPT_DIR"
source "$VENV_DIR/bin/activate"
export VOICE_TYPER_MODEL="${RECOMMENDED_MODEL}"
python3 voice_typer.py "\$@"
LAUNCHER
chmod +x "$SCRIPT_DIR/start.sh"

# --- Create .desktop file ---
echo "▸ Creating desktop entry..."

DESKTOP_FILE="$HOME/.local/share/applications/voice-typer.desktop"
mkdir -p "$(dirname "$DESKTOP_FILE")"

cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=VoiceTyper
Comment=Speech-to-text with global hotkey (Ctrl+Down)
Exec=$SCRIPT_DIR/start.sh
Terminal=false
Type=Application
Icon=audio-input-microphone
Categories=Utility;Audio;
StartupNotify=false
X-GNOME-Autostart-enabled=false
DESKTOP

echo "  ✓ Desktop entry created"

# --- Create autostart entry (optional) ---
cat > "$HOME/.config/autostart/voice-typer.desktop" 2>/dev/null << AUTOSTART || true
[Desktop Entry]
Name=VoiceTyper
Comment=Speech-to-text with global hotkey
Exec=$SCRIPT_DIR/start.sh
Terminal=false
Type=Application
Icon=audio-input-microphone
X-GNOME-Autostart-enabled=true
Hidden=false
AUTOSTART
echo "  ✓ Autostart entry created (disable in Startup Applications if unwanted)"

# --- Done ---
echo
echo "╔══════════════════════════════════════════════════╗"
echo "║        ✓ Installation complete!                  ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║                                                  ║"
echo "║  Start:    ./start.sh                            ║"
echo "║  Model:    $RECOMMENDED_MODEL"
printf "║  %-48s ║\n" ""
echo "║  Hotkey:   Ctrl + ↓ (Down Arrow)                 ║"
echo "║                                                  ║"
echo "║  Change model via env var:                       ║"
echo "║  VOICE_TYPER_MODEL=large-v3 ./start.sh           ║"
echo "║                                                  ║"
echo "║  Models (quality vs speed):                      ║"
echo "║    base   → fastest, ~1GB VRAM                   ║"
echo "║    small  → fast, ~2GB VRAM                      ║"
echo "║    medium → balanced, ~5GB VRAM                  ║"
echo "║    large-v3 → best, ~10GB VRAM                   ║"
echo "║                                                  ║"
echo "╚══════════════════════════════════════════════════╝"
