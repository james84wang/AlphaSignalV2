# AlphaSignal

Personal US equity analysis and trading strategy engine.

---

## Prerequisites

### macOS

**1. Install Python 3.11+**
```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/homebrew/install/HEAD/install.sh)"

# Install Python 3.11
brew install python@3.11
```

**2. Install Node.js LTS**
```bash
brew install node
```

---

### Windows

**1. Install Python 3.11+**
- Download from https://www.python.org/downloads/
- During install, tick **"Add Python to PATH"** before clicking Install Now.

**2. Install Node.js LTS**
- Download from https://nodejs.org/en/download/
- Run the installer with default settings.

---

## Setup (macOS & Windows)

### 1. Create the Python virtual environment

**macOS / Linux:**
```bash
cd AlphaSignalV2
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Windows (PowerShell):**
```powershell
cd AlphaSignalV2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 2. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Run

### macOS / Linux — one command:
```bash
bash scripts/dev.sh
```

### Windows — one command:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Open **http://localhost:5173** in your browser. You should see the AlphaSignal health card.

---

## Run tests

```bash
# Make sure .venv is active first
pytest -q
```

---

## Project layout

```
AlphaSignalV2/
  config.yaml          # all strategy weights & thresholds — edit here
  pyproject.toml       # Python deps
  backend/
    app/
      main.py          # FastAPI entry (GET /health)
      config.py        # loads & validates config.yaml
    tests/
  frontend/
    src/
      App.tsx          # health-check UI
      lib/api.ts       # fetch wrapper
  scripts/
    dev.sh             # start both servers (mac/linux)
    dev.ps1            # start both servers (windows)
  trading_strategy_spec.md
  config.yaml
```
