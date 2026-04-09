$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

$RepoPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$IconDir = Join-Path $RepoPath 'static'
$IconPath = Join-Path $IconDir 'space-invaders.ico'
$PngPath = Join-Path $IconDir 'space-invaders.png'
$LauncherScript = Join-Path $RepoPath 'launch_landing_manager.ps1'
$LocalIconDir = Join-Path $env:LOCALAPPDATA 'AI-Local-Suite'
$LocalIconPath = Join-Path $LocalIconDir 'space-invaders.ico'

if (-not (Test-Path $IconDir)) {
    New-Item -Path $IconDir -ItemType Directory | Out-Null
}
if (-not (Test-Path $LocalIconDir)) {
    New-Item -Path $LocalIconDir -ItemType Directory | Out-Null
}

$size = 256
$pixel = 16
$offsetX = 16
$offsetY = 32

$bmp = New-Object System.Drawing.Bitmap $size, $size
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::None
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$g.Clear([System.Drawing.Color]::FromArgb(18, 24, 44))

$starBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(140, 180, 255))
$g.FillRectangle($starBrush, 20, 20, 3, 3)
$g.FillRectangle($starBrush, 220, 36, 2, 2)
$g.FillRectangle($starBrush, 196, 210, 2, 2)
$g.FillRectangle($starBrush, 48, 220, 3, 3)

$rows = @(
    '0000011001100000',
    '0001111111110000',
    '0011111111111000',
    '0111101101101100',
    '1111111111111110',
    '1110111111110111',
    '1111111111111111',
    '0011100000011100',
    '0110000000000110',
    '1100000000000011'
)

$alienBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(102, 255, 146))
$shadowBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(40, 120, 80))

for ($y = 0; $y -lt $rows.Count; $y++) {
    $row = $rows[$y]
    for ($x = 0; $x -lt $row.Length; $x++) {
        if ($row[$x] -eq '1') {
            $px = $offsetX + ($x * $pixel)
            $py = $offsetY + ($y * $pixel)
            $g.FillRectangle($shadowBrush, $px + 2, $py + 2, $pixel - 2, $pixel - 2)
            $g.FillRectangle($alienBrush, $px, $py, $pixel - 2, $pixel - 2)
        }
    }
}

$beamBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 209, 102))
$g.FillRectangle($beamBrush, 118, 208, 20, 24)
$g.FillRectangle($beamBrush, 112, 232, 32, 8)

$bmp.Save($PngPath, [System.Drawing.Imaging.ImageFormat]::Png)

$icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
$fs = [System.IO.File]::Open($IconPath, [System.IO.FileMode]::Create)
$icon.Save($fs)
$fs.Close()
[System.IO.File]::Copy($IconPath, $LocalIconPath, $true)

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'AI Local Suite Landing.lnk'
$wshell = New-Object -ComObject WScript.Shell
$shortcut = $wshell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'powershell.exe'
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$LauncherScript`""
$shortcut.WorkingDirectory = $RepoPath
$shortcut.IconLocation = "$LocalIconPath,0"
$shortcut.Description = 'Lanza AI Local Suite Landing Manager con icono Space Invaders'
$shortcut.Save()

Write-Host "[OK] Shortcut creado: $shortcutPath"
Write-Host "[OK] Icono creado: $IconPath"
Write-Host "[OK] Icono local para acceso directo: $LocalIconPath"
