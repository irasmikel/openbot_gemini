@echo off
chcp 65001 >nul
title Football Intelligence - Prueba Fase 6
echo ===================================================================
echo   FOOTBALL INTELLIGENCE - PRUEBA DE LA FASE 6 - TELEGRAM Y ALERTAS
echo ===================================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No se encuentra el entorno virtual .venv. Ejecuta primero la Fase 2.
    pause
    exit /b 1
)

echo Ejecutando pruebas del Comunicador de Telegram y Filtro Anti-Spam...
echo.
.venv\Scripts\python.exe scripts/verify_phase6.py

echo.
echo ===================================================================
echo   PRUEBA DE FASE 6 FINALIZADA.
echo ===================================================================
pause
