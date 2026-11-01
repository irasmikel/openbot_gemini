@echo off
chcp 65001 >nul
title Subir Football Intelligence a GitHub
echo ===================================================================
echo   DESPLIEGUE AUTOMATICO A GITHUB: irasmikel/openbot_gemini
echo ===================================================================
echo.

cd /d "%~dp0"

echo [1/6] Configurando identidad local de Git...
git config user.name "irasmikel"
git config user.email "irasmikel@users.noreply.github.com"

echo [2/6] Inicializando repositorio Git local...
if not exist ".git" (
    git init
)
git branch -M main

echo [3/6] Vinculando con https://github.com/irasmikel/openbot_gemini.git ...
git remote remove origin >nul 2>nul
git remote add origin https://github.com/irasmikel/openbot_gemini.git

echo [4/6] Preparando archivos (excluyendo .venv y .env por seguridad)...
git add .

echo [5/6] Creando paquete de subida (commit)...
git commit -m "Despliegue completo Football Intelligence V3 + GitHub Actions"

echo [6/6] Subiendo codigo a GitHub...
git push -u origin main --force

echo.
echo ===================================================================
echo   PROCESO FINALIZADO. Revisa tu web de GitHub!
echo ===================================================================
pause