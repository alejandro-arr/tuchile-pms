$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = "C:\Users\janoa\Desktop\proyectoTUCHILE\.venv\Scripts\python.exe"
if (-not (Test-Path $py -ErrorAction SilentlyContinue)) {
    $py = "C:\Users\janoa\Desktop\TUCHILE_PMS\codigo\venv\Scripts\python.exe"
}

Write-Host "=== 1. Aplicando migraciones y cargando datos iniciales de Turismo TUCHILE ===" -ForegroundColor Cyan
& $py manage.py migrate
& $py seed_data.py

Write-Host "=== 2. Ejecutando Auditoría en Vivo: 9 Pruebas de Patrones GoF y Controles ISO 27001 ===" -ForegroundColor Cyan
& $py manage.py test pms -v 2

if ($args -contains "--runserver") {
    Write-Host ""
    Write-Host "=========================================================================" -ForegroundColor Green
    Write-Host " PMS TURISMO TUCHILE LISTO -> http://127.0.0.1:8000/ " -ForegroundColor Green
    Write-Host " Usuarios (clave: tuchile2026):" -ForegroundColor Green
    Write-Host "   - Superadmin : ttapia@tuchile.cl" -ForegroundColor Yellow
    Write-Host "   - Recepción  : recepcion.tabo@tuchile.cl" -ForegroundColor Yellow
    Write-Host "   - Aseo Móvil : aseo.tabo@tuchile.cl" -ForegroundColor Yellow
    Write-Host "=========================================================================" -ForegroundColor Green
    & $py manage.py runserver 127.0.0.1:8000
}
