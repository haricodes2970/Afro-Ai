#Requires -Version 5.1
<#
.SYNOPSIS
    One-command installer for Project Afro.
    Safe to run multiple times (idempotent).
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_ROOT = Split-Path -Parent $PSScriptRoot
$REQ_FILE  = Join-Path $REPO_ROOT "requirements.txt"

function Write-Step  { param([string]$msg) Write-Host "`n[AFRO] $msg" -ForegroundColor Cyan   }
function Write-Ok    { param([string]$msg) Write-Host "  [OK] $msg"   -ForegroundColor Green  }
function Write-Warn  { param([string]$msg) Write-Host "  [!!] $msg"   -ForegroundColor Yellow }
function Write-Fail  { param([string]$msg) Write-Host " [ERR] $msg"   -ForegroundColor Red    }

# ── 1. Python version check ──────────────────────────────────────────────────

Write-Step "Checking Python version..."

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $pythonCmd = $cmd
                Write-Ok "Found $ver (via '$cmd')"
                break
            } else {
                Write-Warn "$ver found via '$cmd' — Python 3.10+ required."
            }
        }
    } catch {
        # Command not found — try next
    }
}

if (-not $pythonCmd) {
    Write-Fail "Python 3.10 or higher not found."
    Write-Fail "Install from https://www.python.org/downloads/ and re-run this script."
    exit 1
}

# ── 2. pip / requirements ────────────────────────────────────────────────────

Write-Step "Installing Python dependencies from requirements.txt..."

if (-not (Test-Path $REQ_FILE)) {
    Write-Fail "requirements.txt not found at: $REQ_FILE"
    exit 1
}

try {
    & $pythonCmd -m pip install --upgrade pip --quiet
    Write-Ok "pip upgraded."
} catch {
    Write-Warn "pip upgrade failed (non-fatal): $_"
}

try {
    & $pythonCmd -m pip install -r $REQ_FILE
    if ($LASTEXITCODE -ne 0) { throw "pip returned exit code $LASTEXITCODE" }
    Write-Ok "All requirements installed."
} catch {
    Write-Fail "Dependency installation failed: $_"
    exit 1
}

# ── 3. VS Code check / PATH fix ──────────────────────────────────────────────

Write-Step "Checking VS Code (code command)..."

$codeFound = $false
try {
    $null = & code --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $codeFound = $true
        Write-Ok "'code' command available in PATH."
    }
} catch {
    # not in PATH yet
}

if (-not $codeFound) {
    Write-Warn "'code' not in PATH. Searching common install locations..."

    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin",
        "$env:ProgramFiles\Microsoft VS Code\bin",
        "${env:ProgramFiles(x86)}\Microsoft VS Code\bin",
        "$env:USERPROFILE\AppData\Local\Programs\Microsoft VS Code\bin",
    )

    $vscodeBin = $null
    foreach ($path in $candidates) {
        if (Test-Path (Join-Path $path "code.cmd")) {
            $vscodeBin = $path
            break
        }
    }

    if ($vscodeBin) {
        # Add to current session PATH
        $env:PATH = "$vscodeBin;$env:PATH"
        Write-Ok "VS Code bin added to session PATH: $vscodeBin"

        # Persist to user PATH in registry (system-level, survives reboot)
        try {
            $regPath    = "HKCU:\Environment"
            $currentPath = (Get-ItemProperty -Path $regPath -Name Path -ErrorAction SilentlyContinue).Path
            if ($currentPath -notlike "*$vscodeBin*") {
                $newPath = "$vscodeBin;$currentPath"
                Set-ItemProperty -Path $regPath -Name Path -Value $newPath
                Write-Ok "VS Code bin persisted to user PATH in registry."
                Write-Warn "Restart your terminal for the PATH change to take effect globally."
            } else {
                Write-Ok "VS Code bin already in user PATH registry entry."
            }
        } catch {
            Write-Warn "Could not persist to registry (non-fatal): $_"
        }

        # Verify
        try {
            $null = & code --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "'code' command now working."
            } else {
                Write-Warn "'code' found but returned non-zero. Check VS Code installation."
            }
        } catch {
            Write-Warn "Verification failed: $_"
        }
    } else {
        Write-Warn "VS Code not found in standard locations."
        Write-Warn "Install from https://code.visualstudio.com/ and ensure 'Add to PATH' is checked."
        Write-Warn "Afro will still run — VS Code features will fail until 'code' is in PATH."
    }
}

# ── 4. openwakeword model pre-fetch ─────────────────────────────────────────

Write-Step "Pre-fetching hey_jarvis wake-word model..."

try {
    & $pythonCmd -c "from openwakeword.utils import download_models; download_models(['hey_jarvis'])"
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "hey_jarvis model ready."
    } else {
        Write-Warn "Model download returned non-zero. Will retry at first launch."
    }
} catch {
    Write-Warn "Model pre-fetch failed (non-fatal): $_"
    Write-Warn "Afro will attempt to download the model on first launch."
}

# ── 5. Summary ───────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Afro installation complete." -ForegroundColor Green
Write-Host "  Start with:  python core/main.py"          -ForegroundColor White
Write-Host "  Dashboard:   http://127.0.0.1:5000"        -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
