# build_client.ps1 - Build the data_receive.exe client

# Ensure PyInstaller is installed
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Installing PyInstaller..."
    pip install pyinstaller
}

# Clean previous builds
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

Write-Host "Building data_receive.exe..."

# --onefile: Generate a single .exe
# --add-data: Bundle the root certificate inside the exe
# --name: Output filename
# --hidden-import: Ensure sensor2 is found (though auto-detection usually works)

python -m PyInstaller --noconfirm --onefile --clean `
    --name "gcu_bridge_client" `
    --add-data "certs/SCRoot2ca.cer;certs" `
    --hidden-import "app.sensor2" `
    --paths "app" `
    data_receive.py

Write-Host "Build complete. Check 'dist/gcu_bridge_client.exe'."
Write-Host "Remember to ship 'config.secure.ini' alongside the exe!"
