@echo off
rem Instalador local de la plataforma (Windows).
rem Comprueba Python, pasa las pruebas y abre el panel en el navegador.
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    echo Falta Python 3. Descargalo de https://www.python.org/downloads/
    echo   y durante la instalacion marca la casilla "Add python.exe to PATH".
    echo Despues vuelve a hacer doble clic en este archivo.
    pause
    exit /b 1
  )
)

%PY% --version
echo Comprobando la instalacion (unos segundos)...
%PY% -m unittest discover -s tests -t . >nul 2>nul
if errorlevel 1 (
  echo Las pruebas han fallado; ejecuta esto en una consola para ver el detalle:
  echo   %PY% -m unittest discover -s tests -t .
  pause
  exit /b 1
)
echo Pruebas: OK

echo.
echo Todo listo. Abriendo el panel en http://127.0.0.1:8000
echo (cierra esta ventana para parar; solo escucha en este ordenador)
%PY% -m plataforma.cli web
pause
