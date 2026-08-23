"""Panel web: servidor HTTP minimo (solo biblioteca estandar).

    python -m plataforma.cli web --puerto 8000

Sirve el panel estatico de `plataforma/web` y una pequena API JSON. Escucha en
127.0.0.1 salvo que se indique otra cosa: el panel no tiene autenticacion, asi
que no conviene exponerlo a Internet.
"""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import __version__, montecarlo
from .backtest import MotorBacktest
from .bot import Bot
from .config import Config
from .datos import ErrorDatos, crear_proveedor
from .estrategias import ESTRATEGIAS, crear_estrategia
from .optimizador import optimizar

CARPETA_WEB = os.path.join(os.path.dirname(__file__), "web")
TAMANO_MAXIMO_PETICION = 256 * 1024


class _Manejador(BaseHTTPRequestHandler):
    server_version = f"plataforma/{__version__}"
    config: Config = Config()
    candado = threading.Lock()

    # ------------------------------------------------------------- utilidades
    def _json(self, datos, codigo: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _cuerpo(self) -> dict:
        longitud = int(self.headers.get("Content-Length") or 0)
        if longitud <= 0:
            return {}
        if longitud > TAMANO_MAXIMO_PETICION:
            raise ValueError("peticion demasiado grande")
        try:
            return json.loads(self.rfile.read(longitud).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"JSON no valido: {exc}") from exc

    def log_message(self, formato: str, *args) -> None:  # menos ruido en consola
        if os.environ.get("PLATAFORMA_VERBOSA"):
            super().log_message(formato, *args)

    # ------------------------------------------------------------------- rutas
    def do_GET(self) -> None:  # noqa: N802 (nombre impuesto por BaseHTTPRequestHandler)
        ruta = urlparse(self.path).path
        try:
            if ruta == "/api/estrategias":
                return self._json({
                    "estrategias": [
                        {"nombre": n, "descripcion": c.descripcion,
                         "minimo_barras": getattr(c, "minimo_barras", 2)}
                        for n, c in ESTRATEGIAS.items()
                    ],
                    "version": __version__,
                })
            if ruta == "/api/config":
                return self._json(self.config.a_dict())
            if ruta == "/api/estado":
                with self.candado:
                    return self._json(Bot(self.config).estado())
            return self._estatico(ruta)
        except Exception as exc:  # noqa: BLE001 - la API nunca debe tumbar el servidor
            return self._json({"error": str(exc)}, 500)

    def do_POST(self) -> None:  # noqa: N802
        ruta = urlparse(self.path).path
        try:
            cuerpo = self._cuerpo()
            if ruta == "/api/backtest":
                return self._json(self._backtest(cuerpo))
            if ruta == "/api/montecarlo":
                return self._json(self._montecarlo(cuerpo))
            if ruta == "/api/optimizar":
                return self._json(self._optimizar(cuerpo))
            if ruta == "/api/ciclo":
                with self.candado:
                    return self._json(Bot(self._config_peticion(cuerpo)).ejecutar_ciclo())
            if ruta == "/api/reiniciar":
                with self.candado:
                    bot = Bot(self._config_peticion(cuerpo))
                    bot.reiniciar()
                    return self._json(bot.estado())
            return self._json({"error": "ruta desconocida"}, 404)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": str(exc)}, 500)

    # --------------------------------------------------------------- acciones
    def _config_peticion(self, cuerpo: dict) -> Config:
        config = Config(**self.config.a_dict())
        if cuerpo.get("simbolos"):
            simbolos = cuerpo["simbolos"]
            if isinstance(simbolos, str):
                simbolos = [s.strip().upper() for s in simbolos.split(",") if s.strip()]
            config.simbolos = [str(s).strip().upper() for s in simbolos][:20]
        if cuerpo.get("estrategia"):
            if cuerpo["estrategia"] not in ESTRATEGIAS:
                raise ValueError(f"estrategia desconocida: {cuerpo['estrategia']}")
            config.estrategia = cuerpo["estrategia"]
        if cuerpo.get("capital") is not None:
            config.capital = max(1.0, min(float(cuerpo["capital"]), 1_000_000.0))
        if cuerpo.get("dias") is not None:
            config.dias = max(60, min(int(cuerpo["dias"]), 5000))
        if cuerpo.get("proveedor"):
            config.proveedor = str(cuerpo["proveedor"])
        if cuerpo.get("comision") is not None:
            config.costes["comision_fija"] = max(0.0, float(cuerpo["comision"]))
        if cuerpo.get("riesgo") is not None:
            config.riesgo["riesgo_por_operacion"] = min(max(float(cuerpo["riesgo"]), 0.001), 0.5)
        return config

    def _datos(self, config: Config) -> tuple[dict, list[str]]:
        proveedor = crear_proveedor(config.proveedor)
        datos, errores = {}, []
        for simbolo in config.simbolos:
            try:
                datos[simbolo] = proveedor.historico(simbolo, config.dias)
            except ErrorDatos as exc:
                errores.append(f"{simbolo}: {exc}")
        if not datos:
            raise ValueError("no se pudo obtener ningun dato: " + "; ".join(errores))
        avisos = [a for a in getattr(proveedor, "avisos", []) if "SIMULADA" in a]
        return datos, avisos + errores

    def _backtest(self, cuerpo: dict) -> dict:
        config = self._config_peticion(cuerpo)
        datos, avisos = self._datos(config)
        resultado = MotorBacktest(crear_estrategia(config.estrategia), config.capital,
                                  config.objeto_costes(), config.objeto_riesgo()).ejecutar(datos)
        referencia = MotorBacktest(crear_estrategia("comprar_y_mantener"), config.capital,
                                   config.objeto_costes(),
                                   config.objeto_riesgo()).ejecutar(datos)
        salida = resultado.a_dict()
        salida["avisos"] = avisos + salida["avisos"]
        salida["referencia"] = {
            "capital_final": round(referencia.capital_final, 2),
            "rendimiento_total": referencia.metricas["rendimiento_total"],
            "curva": [[f, round(v, 4)] for f, v in referencia.curva],
        }
        salida["estrategia"] = config.estrategia
        salida["simbolos"] = config.simbolos
        return salida

    def _montecarlo(self, cuerpo: dict) -> dict:
        config = self._config_peticion(cuerpo)
        datos, avisos = self._datos(config)
        resultado = MotorBacktest(crear_estrategia(config.estrategia), config.capital,
                                  config.objeto_costes(), config.objeto_riesgo()).ejecutar(datos)
        objetivo = min(max(float(cuerpo.get("objetivo", 2.0)), 1.01), 100.0)
        horizonte = min(max(int(cuerpo.get("horizonte", 100)), 5), 5000)
        simulaciones = min(max(int(cuerpo.get("simulaciones", 5000)), 100), 50_000)
        metodo = cuerpo.get("metodo", "operaciones")
        if metodo == "diario":
            mc = montecarlo.desde_curva(resultado.curva, config.capital, horizonte=horizonte,
                                        simulaciones=simulaciones, objetivo=objetivo)
        else:
            mc = montecarlo.desde_operaciones(resultado.operaciones, config.capital,
                                              horizonte=horizonte, simulaciones=simulaciones,
                                              objetivo=objetivo)
        return {"montecarlo": mc.a_dict(), "metricas": resultado.metricas, "avisos": avisos}

    def _optimizar(self, cuerpo: dict) -> dict:
        config = self._config_peticion(cuerpo)
        datos, avisos = self._datos(config)
        combinaciones, diagnostico = optimizar(
            config.estrategia, datos, config.capital, config.objeto_costes(),
            config.objeto_riesgo(), metrica=cuerpo.get("metrica", "sharpe"))
        return {
            "combinaciones": [c.a_dict() for c in combinaciones[:15]],
            "diagnostico": diagnostico,
            "avisos": avisos,
        }

    # --------------------------------------------------------------- estatico
    def _estatico(self, ruta: str) -> None:
        if ruta in ("/", ""):
            ruta = "/index.html"
        # normalizacion estricta: nada de subir por encima de la carpeta web
        limpio = posixpath.normpath(ruta).lstrip("/")
        destino = os.path.normpath(os.path.join(CARPETA_WEB, limpio))
        if not destino.startswith(os.path.normpath(CARPETA_WEB) + os.sep) \
                or not os.path.isfile(destino):
            self.send_error(404, "no encontrado")
            return
        tipo = mimetypes.guess_type(destino)[0] or "application/octet-stream"
        with open(destino, "rb") as fh:
            contenido = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8" if "text" in tipo
                         or "javascript" in tipo else tipo)
        self.send_header("Content-Length", str(len(contenido)))
        self.end_headers()
        self.wfile.write(contenido)


def crear_servidor(config: Config, puerto: int = 8000,
                   host: str = "127.0.0.1") -> ThreadingHTTPServer:
    manejador = type("ManejadorConfigurado", (_Manejador,), {"config": config})
    return ThreadingHTTPServer((host, puerto), manejador)


def servir(config: Config, puerto: int = 8000, host: str = "127.0.0.1",
           abrir_navegador: bool = True) -> None:
    servidor = crear_servidor(config, puerto, host)
    url = f"http://{host}:{puerto}/"
    print(f"Panel disponible en {url}  (Ctrl+C para parar)")
    print("Modo papel: no se mueve dinero real.")
    if abrir_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParando el panel...")
    finally:
        servidor.server_close()
