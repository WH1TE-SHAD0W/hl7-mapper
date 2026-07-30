# Builds the standalone Windows executable.
#
# Requires the build-time extras, which are NOT runtime dependencies:
#   .venv\Scripts\python.exe -m pip install flet-cli==0.86.4 pyinstaller
#
# Three things here are load-bearing:
#
# --paths=src
#   The hl7msg package lives under src/ and is only importable because main.py
#   puts src/ on sys.path at runtime. PyInstaller analyses imports statically,
#   before that line ever runs, so without this it silently builds an exe that
#   crashes on launch with ModuleNotFoundError.
#
# The `=` form, and only ONE pass-through argument
#   --pyinstaller-build-args takes nargs="*", and argparse refuses a value
#   beginning with "-" unless it is attached with "=". That means exactly one
#   argument can be passed: writing --pyinstaller-build-args="--paths=src
#   --exclude-module=x" hands PyInstaller a single bogus path called
#   "src --exclude-module=x" and produces a broken 9 MB exe that cannot start.
#   To slim the bundle, uninstall what you do not want (see below) rather than
#   trying to pass --exclude-module here.
#
# Keep flet-web out of the build venv
#   Installing flet[desktop] also pulls flet-web, which drags fastapi,
#   starlette, uvicorn, websockets and pydantic into the bundle. A packaged
#   desktop app never serves over HTTP. Removing it costs nothing and saves
#   about a third of the executable:
#     .venv\Scripts\python.exe -m pip uninstall -y flet-web fastapi starlette `
#         uvicorn websockets pydantic pydantic-core
#
# Deliberately NOT $ErrorActionPreference = "Stop": PyInstaller writes its
# INFO log to stderr, and Windows PowerShell turns native-command stderr into
# error records. Under "Stop" the first progress line aborts the build.
# Success is judged by the exit code and the resulting file instead.

& ".\.venv\Scripts\flet.exe" pack main.py `
    --name HL7MessageExplorer `
    --product-name "HL7 Message Data Explorer" `
    --file-description "Flatten and search HL7 v2 XML messages" `
    --product-version "0.1.0" `
    --file-version "0.1.0.0" `
    --yes `
    --pyinstaller-build-args="--paths=src"

$code = $LASTEXITCODE
$exe = ".\dist\HL7MessageExplorer.exe"

if ($code -ne 0) { throw "flet pack exited with code $code" }
if (-not (Test-Path $exe)) { throw "flet pack succeeded but $exe is missing" }

$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Output ""
Write-Output "Built $exe ($mb MB)"
Write-Output "Verify it starts before distributing: run it from a directory"
Write-Output "that contains no source tree."
