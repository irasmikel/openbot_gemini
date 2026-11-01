@echo off
chcp 65001 >nul
title Football Intelligence - Fase 2
echo ===================================================================
echo   FOOTBALL INTELLIGENCE - CONFIGURACION AUTOMATICA EN WINDOWS
echo ===================================================================
echo.

cd /d "%~dp0"

echo [1/4] Comprobando instalacion de Python...
python --version
if %errorlevel% neq 0 (
    echo [ERROR] Python no se encuentra en el PATH de Windows.
    pause
    exit /b 1
)

echo.
echo [2/4] Preparando entorno virtual .venv...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
)

echo.
echo [3/4] Instalando librerias necesarias - puede tardar 1 o 2 minutos...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo [4/4] Ejecutando diagnostico de Fase 2...
echo.
.venv\Scripts\python.exe scripts\verify_phase2.py

echo.
echo ===================================================================
echo   PROCESO COMPLETADO.
echo ===================================================================
pause
