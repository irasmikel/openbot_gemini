@echo off
chcp 65001 >nul
title Football Intelligence - Prueba Fase 4
echo ===================================================================
echo   FOOTBALL INTELLIGENCE - PRUEBA DE LA FASE 4 - ANALISIS PREVIO
echo ===================================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No se encuentra el entorno virtual .venv. Ejecuta primero la Fase 2.
    pause
    exit /b 1
)

echo Ejecutando pruebas del Coordinador, Contexto y Detector Previo...
echo.
.venv\Scripts\python.exe scripts/verify_phase4.py

echo.
echo ===================================================================
echo   PRUEBA DE FASE 4 FINALIZADA.
echo ===================================================================
pause
