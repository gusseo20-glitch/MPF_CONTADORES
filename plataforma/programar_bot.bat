@echo off
title Programar el bot diario
cd /d "%~dp0"

rem Configuracion por defecto del bot: paper de Alpaca, 50, ETFs grandes
py -m plataforma.cli config -s SPY,QQQ -e cruce_medias -c 50 --modo alpaca_papel >nul

rem Ruta de esta carpeta sin la barra final (schtasks se atraganta con ella)
set "AQUI=%~dp0"
set "AQUI=%AQUI:~0,-1%"

schtasks /Create /F /TN "PlataformaInversionBot" /SC DAILY /ST 23:00 ^
  /TR "cmd /c cd /d \"%AQUI%\" && py -m plataforma.cli bot ciclo >> bot.log 2>&1"

if errorlevel 1 (
  echo No se pudo crear la tarea. Copia el error de arriba y pegaselo a Claude.
  pause
  exit /b 1
)
echo.
echo Listo: el bot ejecutara un ciclo TODOS LOS DIAS a las 23:00 (hora local),
echo con la bolsa de EE.UU. ya cerrada; las ordenes entran en la apertura siguiente.
echo Los fines de semana no hay mercado: el ciclo simplemente no opera.
echo.
echo Todo queda apuntado en: %AQUI%\bot.log
echo Para ver la cartera cuando quieras: doble clic en instalar_todo.bat (abre el panel)
echo Para borrar la tarea algun dia:  schtasks /Delete /TN "PlataformaInversionBot" /F
pause
