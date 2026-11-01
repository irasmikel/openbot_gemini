@echo off
chcp 65001 >nul
title Football Intelligence Pro - Sincronizador y Panel Visual
echo ===================================================================
echo   FOOTBALL INTELLIGENCE PRO - SINCRONIZACION DE JORNADA Y PANEL
echo ===================================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No se encuentra el entorno virtual .venv. Ejecuta primero la Fase 2.
    pause
    exit /b 1
)

echo [1/2] Sincronizando partidos de las 7 ligas europeas y ejecutando Agentes...
.venv\Scripts\python.exe scripts/sync_real_matches.py

echo.
echo [2/2] Abriendo la nueva interfaz oscura Football Intelligence Pro...
.venv\Scripts\python.exe -m streamlit run ui/dashboard.py
pause
