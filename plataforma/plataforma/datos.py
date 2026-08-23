"""Proveedores de datos de mercado.

Todos devuelven una lista de `Barra` ordenada de mas antigua a mas reciente.

- `ProveedorYahoo`  : datos reales gratuitos (requiere red).
- `ProveedorStooq`  : alternativa gratuita en CSV (requiere red).
- `ProveedorCSV`    : ficheros locales, para trabajar sin conexion.
- `ProveedorSintetico`: series generadas (movimiento browniano geometrico)
  para pruebas deterministas y para el modo demo.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from .modelos import Barra

CARPETA_CACHE = os.environ.get(
    "PLATAFORMA_CACHE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "datos")
)
CADUCIDAD_CACHE_S = 60 * 60 * 6  # 6 horas
USER_AGENT = "Mozilla/5.0 (compatible; plataforma-inversion/1.0)"


class ErrorDatos(RuntimeError):
    """No se han podido obtener datos de mercado."""


class ProveedorDatos:
    nombre = "base"

    def historico(self, simbolo: str, dias: int = 500, intervalo: str = "1d") -> list[Barra]:
        raise NotImplementedError

    def ultimo_precio(self, simbolo: str) -> float:
        barras = self.historico(simbolo, dias=5)
        if not barras:
            raise ErrorDatos(f"sin datos para {simbolo}")
        return barras[-1].cierre


def _descargar(url: str, tiempo_max: int = 20) -> bytes:
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(peticion, timeout=tiempo_max) as respuesta:
            return respuesta.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise ErrorDatos(f"fallo de red al pedir {url}: {exc}") from exc


def _ruta_cache(clave: str) -> str:
    os.makedirs(CARPETA_CACHE, exist_ok=True)
    seguro = "".join(c if c.isalnum() or c in "-._" else "_" for c in clave)
    return os.path.join(CARPETA_CACHE, f"{seguro}.json")


def leer_cache(clave: str, caducidad: int = CADUCIDAD_CACHE_S) -> list[Barra] | None:
    ruta = _ruta_cache(clave)
    if not os.path.exists(ruta):
        return None
    if time.time() - os.path.getmtime(ruta) > caducidad:
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            return [Barra.desde_dict(d) for d in json.load(fh)]
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def escribir_cache(clave: str, barras: list[Barra]) -> None:
    try:
        with open(_ruta_cache(clave), "w", encoding="utf-8") as fh:
            json.dump([b.a_dict() for b in barras], fh)
    except OSError:
        pass  # la cache es un extra, nunca debe romper la ejecucion


class ProveedorYahoo(ProveedorDatos):
    """Datos diarios de Yahoo Finance (endpoint publico de graficos)."""

    nombre = "yahoo"
    URL = (
        "https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
        "?range={rango}&interval={intervalo}&includePrePost=false"
    )

    def __init__(self, usar_cache: bool = True) -> None:
        self.usar_cache = usar_cache

    @staticmethod
    def _rango(dias: int) -> str:
        for limite, etiqueta in ((5, "5d"), (30, "1mo"), (90, "3mo"), (180, "6mo"),
                                 (365, "1y"), (730, "2y"), (1825, "5y"), (3650, "10y")):
            if dias <= limite:
                return etiqueta
        return "max"

    def historico(self, simbolo: str, dias: int = 500, intervalo: str = "1d") -> list[Barra]:
        clave = f"yahoo_{simbolo}_{intervalo}_{self._rango(dias)}"
        if self.usar_cache:
            guardado = leer_cache(clave)
            if guardado:
                return guardado[-dias:]
        crudo = _descargar(
            self.URL.format(simbolo=urllib.parse.quote(simbolo), rango=self._rango(dias),
                            intervalo=intervalo)
        )
        try:
            datos = json.loads(crudo)
            resultado = datos["chart"]["result"][0]
            marcas = resultado["timestamp"]
            cotiz = resultado["indicators"]["quote"][0]
        except (json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
            raise ErrorDatos(f"respuesta inesperada de Yahoo para {simbolo}") from exc

        barras: list[Barra] = []
        for i, marca in enumerate(marcas):
            cierre = cotiz["close"][i]
            if cierre is None:
                continue
            apertura = cotiz["open"][i] if cotiz["open"][i] is not None else cierre
            maximo = cotiz["high"][i] if cotiz["high"][i] is not None else cierre
            minimo = cotiz["low"][i] if cotiz["low"][i] is not None else cierre
            volumen = cotiz["volume"][i] or 0
            barras.append(
                Barra(
                    fecha=datetime.fromtimestamp(marca, tz=timezone.utc).strftime("%Y-%m-%d"),
                    apertura=float(apertura),
                    maximo=float(maximo),
                    minimo=float(minimo),
                    cierre=float(cierre),
                    volumen=float(volumen),
                )
            )
        if not barras:
            raise ErrorDatos(f"Yahoo no devolvio barras para {simbolo}")
        if self.usar_cache:
            escribir_cache(clave, barras)
        return barras[-dias:]


class ProveedorStooq(ProveedorDatos):
    """Alternativa gratuita en CSV (stooq.com). Simbolos tipo `aapl.us`."""

    nombre = "stooq"
    URL = "https://stooq.com/q/d/l/?s={simbolo}&i=d"

    def __init__(self, usar_cache: bool = True) -> None:
        self.usar_cache = usar_cache

    @staticmethod
    def _normalizar(simbolo: str) -> str:
        s = simbolo.lower()
        return s if "." in s or "^" in s else f"{s}.us"

    def historico(self, simbolo: str, dias: int = 500, intervalo: str = "1d") -> list[Barra]:
        simbolo_stooq = self._normalizar(simbolo)
        clave = f"stooq_{simbolo_stooq}"
        if self.usar_cache:
            guardado = leer_cache(clave)
            if guardado:
                return guardado[-dias:]
        texto = _descargar(self.URL.format(simbolo=simbolo_stooq)).decode("utf-8", "replace")
        barras = _barras_desde_csv(io.StringIO(texto))
        if not barras:
            raise ErrorDatos(f"Stooq no devolvio barras para {simbolo}")
        if self.usar_cache:
            escribir_cache(clave, barras)
        return barras[-dias:]


class ProveedorCSV(ProveedorDatos):
    """Lee `<carpeta>/<simbolo>.csv` con cabecera Date,Open,High,Low,Close,Volume."""

    nombre = "csv"

    def __init__(self, carpeta: str = CARPETA_CACHE) -> None:
        self.carpeta = carpeta

    def historico(self, simbolo: str, dias: int = 500, intervalo: str = "1d") -> list[Barra]:
        ruta = os.path.join(self.carpeta, f"{simbolo}.csv")
        if not os.path.exists(ruta):
            raise ErrorDatos(f"no existe el fichero {ruta}")
        with open(ruta, "r", encoding="utf-8") as fh:
            barras = _barras_desde_csv(fh)
        if not barras:
            raise ErrorDatos(f"{ruta} no contiene barras validas")
        return barras[-dias:]


class ProveedorSintetico(ProveedorDatos):
    """Serie simulada reproducible (para pruebas y modo demo sin red)."""

    nombre = "sintetico"

    def __init__(self, semilla: int = 7, deriva_anual: float = 0.08,
                 volatilidad_anual: float = 0.25, precio_inicial: float = 100.0) -> None:
        self.semilla = semilla
        self.deriva_anual = deriva_anual
        self.volatilidad_anual = volatilidad_anual
        self.precio_inicial = precio_inicial

    #: longitud de la serie canonica; se generan siempre las mismas barras para
    #: un simbolo y se devuelve la cola pedida, de forma que consultar 5 dias o
    #: 500 da precios coherentes entre si.
    LARGO_CANONICO = 2600

    def historico(self, simbolo: str, dias: int = 500, intervalo: str = "1d") -> list[Barra]:
        total = max(dias, self.LARGO_CANONICO)
        rng = random.Random(f"{self.semilla}:{simbolo}")
        mu = self.deriva_anual / 252.0
        sigma = self.volatilidad_anual / math.sqrt(252.0)
        precio = self.precio_inicial
        inicio = date.today() - timedelta(days=int(total * 1.5))
        barras: list[Barra] = []
        dia = inicio
        while len(barras) < total:
            dia += timedelta(days=1)
            if dia.weekday() >= 5:
                continue
            choque = rng.gauss(0.0, 1.0)
            apertura = precio
            precio = max(0.01, precio * math.exp(mu - 0.5 * sigma**2 + sigma * choque))
            maximo = max(apertura, precio) * (1 + abs(rng.gauss(0, sigma / 3)))
            minimo = min(apertura, precio) * (1 - abs(rng.gauss(0, sigma / 3)))
            barras.append(
                Barra(dia.isoformat(), round(apertura, 4), round(maximo, 4),
                      round(minimo, 4), round(precio, 4), float(rng.randint(10_000, 900_000)))
            )
        return barras[-dias:]


def _barras_desde_csv(flujo) -> list[Barra]:
    lector = csv.DictReader(flujo)
    barras: list[Barra] = []
    for fila in lector:
        clave = {k.strip().lower(): v for k, v in fila.items() if k}
        try:
            cierre = float(clave.get("close") or clave.get("cierre"))
        except (TypeError, ValueError):
            continue
        fecha = (clave.get("date") or clave.get("fecha") or "").strip()
        barras.append(
            Barra(
                fecha=fecha,
                apertura=float(clave.get("open") or clave.get("apertura") or cierre),
                maximo=float(clave.get("high") or clave.get("maximo") or cierre),
                minimo=float(clave.get("low") or clave.get("minimo") or cierre),
                cierre=cierre,
                volumen=float(clave.get("volume") or clave.get("volumen") or 0) or 0.0,
            )
        )
    barras.sort(key=lambda b: b.fecha)
    return barras


PROVEEDORES: dict[str, type[ProveedorDatos]] = {
    "yahoo": ProveedorYahoo,
    "stooq": ProveedorStooq,
    "csv": ProveedorCSV,
    "sintetico": ProveedorSintetico,
}


def crear_proveedor(nombre: str = "auto") -> ProveedorDatos:
    """Crea un proveedor. `auto` intenta Yahoo, luego Stooq, luego sintetico."""
    if nombre != "auto":
        if nombre not in PROVEEDORES:
            raise ValueError(f"proveedor desconocido: {nombre}")
        return PROVEEDORES[nombre]()
    return ProveedorAuto()


class ProveedorAuto(ProveedorDatos):
    """Encadena proveedores reales y cae al sintetico si no hay conexion."""

    nombre = "auto"

    def __init__(self) -> None:
        self.cadena: list[ProveedorDatos] = [ProveedorYahoo(), ProveedorStooq()]
        self.respaldo = ProveedorSintetico()
        self.ultimo_usado = ""
        self.avisos: list[str] = []

    def historico(self, simbolo: str, dias: int = 500, intervalo: str = "1d") -> list[Barra]:
        for proveedor in self.cadena:
            try:
                barras = proveedor.historico(simbolo, dias, intervalo)
                self.ultimo_usado = proveedor.nombre
                return barras
            except ErrorDatos as exc:
                self.avisos.append(f"{proveedor.nombre}: {exc}")
        self.ultimo_usado = "sintetico"
        self.avisos.append(
            "Sin acceso a datos reales: usando serie SIMULADA. "
            "Los resultados NO representan el mercado real."
        )
        return self.respaldo.historico(simbolo, dias, intervalo)
