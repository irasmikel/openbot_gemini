@echo off
chcp 65001 >nul
title Subir Actualizacion V4 Bwin a GitHub
echo ===================================================================
echo   ACTUALIZANDO PROYECTO EN GITHUB (MODELO CALIBRADO BWIN + DIRECTO)
echo ===================================================================
echo.

cd /d "%~dp0"

git config user.name "irasmikel"
git config user.email "irasmikel@users.noreply.github.com"

echo [1/3] Preparando archivos calibrados V4...
git add .

echo [2/3] Guardando version calibrada (Bwin + Mensajes Claros + Prepartido 3h)...
git commit -m "Calibracion V4: Cuotas Bwin, mensajes claros sin tecnicismos y avisos <3h y en directo"

echo [3/3] Subiendo a https://github.com/irasmikel/openbot_gemini ...
git push -u origin main --force

echo.
echo ===================================================================
echo   LISTO! Tu sistema en la nube ya esta actualizado con Bwin.
echo ===================================================================
pause
