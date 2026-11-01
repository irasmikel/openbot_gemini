@echo off
chcp 65001 >nul
title Football Intelligence - Prueba Fase 5
echo ===================================================================
echo   FOOTBALL INTELLIGENCE - PRUEBA DE LA FASE 5 - MOTOR EN DIRECTO
echo ===================================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No se encuentra el entorno virtual .venv. Ejecuta primero la Fase 2.
    pause
    exit /b 1
)

echo Ejecutando pruebas del Supervisor y Detector de Partidos en Directo...
echo.
.venv\Scripts\python.exe scripts/verify_phase5.py

echo.
echo ===================================================================
echo   PRUEBA DE FASE 5 FINALIZADA.
echo ===================================================================
pause
