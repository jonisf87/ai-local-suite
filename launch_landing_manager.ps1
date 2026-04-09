$ErrorActionPreference = 'Stop'

$LandingUrl = 'http://127.0.0.1:5000'
$WslDistro = 'Ubuntu'
$WslCommand = 'cd /home/jonathan/ai/ai-local-suite && /home/jonathan/ai/venv/bin/python landing_manager.py'

$up = $false
try {
    $response = Invoke-WebRequest -Uri $LandingUrl -UseBasicParsing -TimeoutSec 2
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        $up = $true
    }
} catch {
    $up = $false
}

if (-not $up) {
    Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d', $WslDistro, 'bash', '-lc', $WslCommand)
    Start-Sleep -Seconds 3
}

Start-Process $LandingUrl
