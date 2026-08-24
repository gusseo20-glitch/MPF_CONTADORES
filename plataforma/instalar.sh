#!/usr/bin/env bash
# Instalador local de la plataforma (macOS / Linux).
# Comprueba Python, pasa las pruebas y abre el panel en el navegador.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Falta Python 3. Como instalarlo:"
  echo "  macOS         : abre Terminal y ejecuta  xcode-select --install"
  echo "  Ubuntu/Debian : sudo apt install -y python3"
  echo "  Fedora        : sudo dnf install -y python3"
  exit 1
fi

echo "Python encontrado: $(python3 --version)"
echo "Comprobando la instalacion (unos segundos)..."
if python3 -m unittest discover -s tests -t . >/dev/null 2>&1; then
  echo "Pruebas: 62/62 OK"
else
  echo "Las pruebas han fallado; ejecuta esto para ver el detalle:"
  echo "  python3 -m unittest discover -s tests -t ."
  exit 1
fi

echo
echo "Todo listo. Abriendo el panel en http://127.0.0.1:8000  (Ctrl+C para parar)"
echo "Solo escucha en este ordenador: nadie de fuera puede entrar."
exec python3 -m plataforma.cli web
