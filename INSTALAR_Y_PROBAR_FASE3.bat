@echo off
chcp 65001 >nul
title Football Intelligence - Prueba Fase 3
echo ===================================================================
echo   FOOTBALL INTELLIGENCE - PRUEBA DE LOS PRIMEROS AGENTES (FASE 3)
echo ===================================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No se encuentra el entorno virtual .venv. Ejecuta primero la Fase 2.
    pause
    exit /b 1
)

echo Ejecutando pruebas del Agente 2 (Estadística), Agente 3 (Cuotas) y Agente 9 (DataGuard)...
echo.
.venv\Scripts\python.exe scripts/verify_phase3.py

echo.
echo ===================================================================
echo   PRUEBA DE FASE 3 FINALIZADA.
echo ===================================================================
pause