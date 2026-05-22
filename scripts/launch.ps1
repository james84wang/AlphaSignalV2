# AlphaSignal — one-click launcher (Windows PowerShell)
#
# What it does:
#   1. Builds the React frontend into frontend\dist\ (skipped if already built)
#   2. Starts the FastAPI backend, which serves the built frontend at http://localhost:8000
#   3. Opens the app in Chrome "app mode" (no address bar — native-window feel)
#      or falls back to Edge / your default browser if Chrome isn't installed.
#
# Usage (run from the AlphaSignalV2\ folder):
#   powershell -ExecutionPolicy Bypass -File scripts\launch.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\launch.ps1 -Rebuild
#
param(
    [switch]$Rebuild
)

$repoRoot  = Split-Path -Parent $PSScriptRoot
$venvPy    = "$repoRoot\.venv\Scripts\python.exe"
$venvUvi   = "$repoRoot\.venv\Scripts\uvicorn.exe"
$dist      = "$repoRoot\frontend\dist\index.html"
$port      = 8000

# ── 1. Check virtual environment ──────────────────────────────────────────────
if (-not (Test-Path $venvPy)) {
    Write-Error "Virtual environment not found at $repoRoot\.venv"
    Write-Host  "Run: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e '.[dev]'"
    exit 1
}

# ── 2. Build frontend if needed ────────────────────────────────────────────────
if (-not (Test-Path $dist) -or $Rebuild) {
    Write-Host "==> Building frontend (this takes ~30 seconds the first time)..."
    Push-Location "$repoRoot\frontend"
    npm install --silent
    npm run build
    Pop-Location
    Write-Host "==> Frontend built successfully."
}

# ── 3. Open browser after a short delay ───────────────────────────────────────
$url = "http://localhost:$port"
Start-Job -ScriptBlock {
    param($u)
    Start-Sleep 3
    # Try Chrome app mode first, then Edge app mode, then default browser.
    $chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
    $edge   = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if (Test-Path $chrome) {
        Start-Process $chrome "--app=$u"
    } elseif (Test-Path $edge) {
        Start-Process $edge "--app=$u"
    } else {
        Start-Process $u
    }
} -ArgumentList $url | Out-Null

Write-Host ""
Write-Host "============================================================"
Write-Host "  AlphaSignal — http://localhost:$port"
Write-Host "  Close this window or press Ctrl-C to stop."
Write-Host "============================================================"
Write-Host ""

# ── 4. Start backend (serves API + static frontend on port 8000) ──────────────
Set-Location $repoRoot
& $venvUvi backend.app.main:app --port $port --host 0.0.0.0
