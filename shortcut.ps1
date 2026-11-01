# Adds a jtop shortcut with its icon to the Start menu, after `pipx install`.
# From a clone: .\shortcut.ps1   Without one: irm https://raw.githubusercontent.com/NotDjz/jtop/main/shortcut.ps1 | iex
# Running it again just rewrites the same shortcut.
$ErrorActionPreference = "Stop"

$exe = (Get-Command jtop -CommandType Application -ErrorAction SilentlyContinue).Source
if (-not $exe) { throw "jtop not found: run 'pipx install git+https://github.com/NotDjz/jtop' first" }

# The icon goes next to pipx's jtop.exe, so the shortcut does not depend on a clone staying where it is.
$icon = Join-Path (Split-Path $exe) "jtop.ico"
$local = if ($PSScriptRoot) { Join-Path $PSScriptRoot "jtop.ico" }
if ($local -and (Test-Path $local)) { Copy-Item $local $icon -Force }
else { Invoke-WebRequest "https://raw.githubusercontent.com/NotDjz/jtop/main/jtop.ico" -OutFile $icon }

$lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "jtop.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $exe
$s.IconLocation = "$icon,0"
$s.Description = "Hardware components and live usage, htop style"
$s.Save()
"Created $lnk"
