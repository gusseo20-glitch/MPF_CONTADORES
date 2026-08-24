@echo off
title Conectar con Alpaca
cd /d "%~dp0"
echo.
echo === Conectar la plataforma con tu cuenta de Alpaca ===
echo.
echo Necesitas las 2 claves del panel de alpaca.markets.
echo Empieza SIEMPRE por las del entorno PAPER (practica, sin dinero real).
echo Nadie mas deberia estar mirando tu pantalla ahora.
echo.
set /p CLAVE="Pega tu API Key ID y pulsa Enter: "
set /p SECRETO="Pega tu Secret Key y pulsa Enter: "
if "%CLAVE%"=="" echo No has escrito nada. & pause & exit /b 1
if "%SECRETO%"=="" echo Falta la Secret Key. & pause & exit /b 1

rem Guardarlas en TU usuario de Windows (no van al repositorio ni a internet)
setx APCA_API_KEY_ID "%CLAVE%" >nul
setx APCA_API_SECRET_KEY "%SECRETO%" >nul
rem ...y en esta misma ventana, para probar ya
set "APCA_API_KEY_ID=%CLAVE%"
set "APCA_API_SECRET_KEY=%SECRETO%"

echo.
echo Claves guardadas. Probando la conexion con Alpaca...
echo.
py -m plataforma.cli cuenta --modo alpaca_papel
echo.
echo Si arriba ves tu cuenta (estado ACTIVE), el enlace funciona.
echo Si ves un error de credenciales, vuelve a ejecutar este archivo y
echo repasa que copiaste las claves completas.
pause
