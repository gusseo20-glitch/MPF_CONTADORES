@echo off
title Plataforma de inversion - instalador
echo Descargando y ejecutando el instalador...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm 'https://github.com/gusseo20-glitch/MPF_CONTADORES/raw/claude/plataforma-inversion-automatica-wx1zl4/plataforma/instalar_todo.ps1' | iex"
pause
