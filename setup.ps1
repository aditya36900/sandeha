<#
.SYNOPSIS
  One-command setup for Sandeha on Windows.
.DESCRIPTION
  Creates .venv, installs PyTorch (CUDA if an NVIDIA GPU is found, otherwise CPU), the Python packages, the public
  datasets and local AI models, builds the dashboard, then checks the install.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\setup.ps1
  .\setup.ps1 -Cpu            # force CPU PyTorch
  .\setup.ps1 -SkipData       # skip the ~9 GB of datasets and models (download later)
  .\setup.ps1 -BigVlm         # also download Qwen2.5-VL-7B (16 GB, needs a GPU with ~8 GB free)
  .\setup.ps1 -NoExtras       # skip optional packages (bitsandbytes, accelerate, cascadio, pypdf)
#>
param([switch]$Cpu, [switch]$SkipData, [switch]$BigVlm, [switch]$NoExtras)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

Step "Checking Python (3.10 to 3.13, 3.12 recommended)"
$py = $null
foreach ($cand in @("py -3.12", "py -3.11", "py -3.13", "python")) {
    try {
        $ver = & cmd /c "$cand --version 2>&1"
        if ($ver -match "Python 3\.(1[0-3])\.") { $py = $cand; break }
    } catch {}
}
if (-not $py) { Fail "Python 3.10-3.13 not found. Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add to PATH')." }
Write-Host "using: $py ($ver)"

Step "Checking Node.js (18 or newer)"
try { $node = (node --version) } catch { Fail "Node.js not found. Install the LTS from https://nodejs.org/" }
if ([int]($node.TrimStart('v').Split('.')[0]) -lt 18) { Fail "Node $node is too old; install Node 18+." }
Write-Host "node $node"

Step "Creating the virtual environment (.venv)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & cmd /c "$py -m venv .venv"; if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" } }
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet

Step "Installing PyTorch"
$gpu = $false
if (-not $Cpu) { try { nvidia-smi --query-gpu=name --format=csv,noheader | Out-Null; if ($LASTEXITCODE -eq 0) { $gpu = $true } } catch {} }
if ($gpu) {
    Write-Host "NVIDIA GPU found: installing CUDA 12.8 build"
    & $vpy -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
} else {
    Write-Host "no NVIDIA GPU (or -Cpu): installing CPU build"
    & $vpy -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu
}
if ($LASTEXITCODE -ne 0) { Fail "PyTorch install failed" }

Step "Installing Python packages"
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "requirements install failed" }
if (-not $NoExtras) {
    & $vpy -m pip install -r requirements-extra.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "optional extras failed to install; the station still runs without them" -ForegroundColor DarkYellow }
}

if (-not $SkipData) {
    Step "Downloading public datasets and local AI models (one time, ~9 GB)"
    $dl = @("backend\scripts\download_data.py")
    if ($BigVlm) { $dl += "--big-vlm" }
    & $vpy @dl
    if ($LASTEXITCODE -ne 0) { Fail "download failed: re-run .\setup.ps1 (finished parts are kept)" }
} else { Write-Host "skipping data (run later: .venv\Scripts\python backend\scripts\download_data.py)" }

Step "Building the dashboard"
Push-Location frontend
if (Test-Path "package-lock.json") { npm ci } else { npm install }
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "npm install failed" }
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "dashboard build failed" }
Pop-Location

Step "Checking the install"
& $vpy backend\scripts\check_install.py
Write-Host "`nDone. Start the station with:  .\run.ps1      (or .\run.ps1 -Dev for hot reload)" -ForegroundColor Green
