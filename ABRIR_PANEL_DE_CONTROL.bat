@echo off
chcp 65001 >nul
title Football Intelligence - Panel de Control Windows
echo ===================================================================
echo   FOOTBALL INTELLIGENCE - INICIANDO PANEL DE CONTROL VISUAL
echo ===================================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No se encuentra el entorno virtual .venv. Ejecuta primero la Fase 2.
    pause
    exit /b 1
)

echo [1/2] Ejecutando auditoria de calibracion Brier Score - Fase 8...
.venv\Scripts\python.exe scripts/verify_phase8.py

echo.
echo [2/2] Abriendo el Panel de Control Visual en tu navegador predeterminado...
echo Para cerrar el Panel de Control cuando termines, cierra esta ventana negra.
echo.
.venv\Scripts\python.exe -m streamlit run ui/dashboard.py
pause
