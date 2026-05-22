# Start backend (FastAPI) and frontend (Vite) on Windows.
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "==> Starting AlphaSignal dev servers..."
Write-Host "    Backend:  http://localhost:8000"
Write-Host "    Frontend: http://localhost:5173"
Write-Host "    Close this window or press Ctrl-C to stop both."
Write-Host ""

# Backend
$backendJob = Start-Job -ScriptBlock {
    param($root)
    Set-Location $root
    uvicorn backend.app.main:app --reload --port 8000
} -ArgumentList $repoRoot

# Frontend
$frontendJob = Start-Job -ScriptBlock {
    param($root)
    Set-Location "$root\frontend"
    npm run dev
} -ArgumentList $repoRoot

try {
    Receive-Job $backendJob, $frontendJob -Wait -AutoRemoveJob
} finally {
    Stop-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
}
