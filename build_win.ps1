#Requires -Version 7.2
# Builds dist\jtop.exe (Python, psutil and windows-curses inside) and publishes it in the GitHub release
# v<VERSION>, the Windows counterpart of build.sh. Needs PyInstaller, psutil and windows-curses under `python`,
# and gh logged in. -NoPublish stops after the self-test. Running it again replaces the release's jtop.exe.
param([switch]$NoPublish)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$version = (Select-String -Path "$root\pyproject.toml" -Pattern '^version = "(.+?)"').Matches[0].Groups[1].Value

# jtop.py as data: jtop_fun's hacker_typer pane reads it beside its own file, the unpacked folder in the exe
python -m PyInstaller --onefile --clean -y --name jtop --icon "$root\jtop.ico" --add-data "$root\jtop.py;." `
    --specpath "$root\build" --workpath "$root\build" --distpath "$root\dist" "$root\jtop_win.py"
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$check = & "$root\dist\jtop.exe" --check 2>&1
if ("$check".Trim() -ne "ok") { throw "dist\jtop.exe --check failed: $check" }
"dist\jtop.exe ${version}: ok"
if ($NoPublish) { return }

# the tag must point at the code the exe was built from
git -C $root diff --quiet HEAD
if ($LASTEXITCODE) { throw "uncommitted changes: commit them first" }
$head = git -C $root rev-parse HEAD
if (-not (git -C $root branch -r --contains $head)) { throw "HEAD is not pushed: push it first" }

gh release view "v$version" -R NotDjz/jtop *> $null
if ($LASTEXITCODE) {
    gh release create "v$version" "$root\dist\jtop.exe" -R NotDjz/jtop --target $head --title "jtop $version" `
        --generate-notes
} else {
    gh release upload "v$version" "$root\dist\jtop.exe" -R NotDjz/jtop --clobber
}
if ($LASTEXITCODE) { throw "gh release failed" }
