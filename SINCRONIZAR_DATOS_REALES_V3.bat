@echo off
chcp 65001 >nul
title Football Intelligence V3 - Datos 100% Reales y Nueva Interfaz
echo ===================================================================
echo   FOOTBALL INTELLIGENCE V3 - LIMPIEZA Y DATOS 100%% REALES
echo ===================================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No se encuentra el entorno virtual .venv. Ejecuta primero la Fase 2.
    pause
    exit /b 1
)

echo [1/2] Eliminando datos de prueba y descargando partidos, clasificaciones y cuotas reales...
.venv\Scripts\python.exe scripts/sync_real_matches.py

echo.
echo [2/2] Abriendo el Centro de Decision Football Intelligence V3...
.venv\Scripts\python.exe -m streamlit run ui/dashboard.py
pause
