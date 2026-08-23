"""Conexion con el broker Alpaca: ordenes reales con tus propias claves.

Alpaca (alpaca.markets) es un broker estadounidense con API publica, sin
comisiones y con fracciones de accion desde 1 USD. Para una cuenta de 50 EUR
es el formato que hace viable operar de verdad: una comision fija de 1 EUR
por orden se comeria la cuenta en semanas.

Dos entornos con LA MISMA API:

  - ``paper-api.alpaca.markets``  cuenta de practica del propio broker,
    gratuita y sin dinero real. Es el primer paso obligado.
  - ``api.alpaca.markets``        dinero real.

Credenciales SIEMPRE por variables de entorno, nunca en ficheros del repo::

    export APCA_API_KEY_ID="tu clave"
    export APCA_API_SECRET_KEY="tu secreto"

Y el modo real exige ademas una confirmacion explicita e inequivoca::

    export PLATAFORMA_DINERO_REAL=acepto

Notas que importan:

* Alpaca opera bolsa de EE. UU. en dolares: al depositar euros se convierten.
* Las compras se mandan por importe (*notional*), que permite fracciones; las
  ventas, por cantidad. Ordenes a mercado con vigencia de un dia.
* Si el mercado esta cerrado, la orden queda en cola y se ejecuta en la
  apertura siguiente — exactamente la hipotesis del backtest. En ese caso el
  precio local es una estimacion hasta que ``bot sincronizar`` lo cuadre con
  el broker.
* Cada orden lleva un identificador derivado de la fecha y el simbolo: si el
  cron lanza el ciclo dos veces el mismo dia, el broker rechaza el duplicado
  y la plataforma recupera la orden original en lugar de comprar dos veces.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .broker import BrokerBase, Ejecucion

URL_PAPEL = "https://paper-api.alpaca.markets"
URL_REAL = "https://api.alpaca.markets"
ESTADOS_TERMINALES = {"filled", "canceled", "expired", "rejected", "done_for_day"}


class ErrorAlpaca(RuntimeError):
    """Fallo hablando con la API de Alpaca."""


def _credencial(*nombres: str) -> str:
    for nombre in nombres:
        valor = os.environ.get(nombre, "").strip()
        if valor:
            return valor
    return ""


class ClienteAlpaca:
    """Cliente minimo de la API de trading de Alpaca (solo stdlib)."""

    def __init__(self, clave: str | None = None, secreto: str | None = None,
                 papel: bool = True, transporte=None, tiempo_max: int = 20) -> None:
        self.clave = clave or _credencial("APCA_API_KEY_ID", "ALPACA_KEY_ID")
        self.secreto = secreto or _credencial("APCA_API_SECRET_KEY", "ALPACA_SECRET_KEY")
        self.papel = papel
        self.base = URL_PAPEL if papel else URL_REAL
        self.tiempo_max = tiempo_max
        self._transporte = transporte or self._http
        if not self.clave or not self.secreto:
            raise ErrorAlpaca(
                "faltan credenciales: exporta APCA_API_KEY_ID y APCA_API_SECRET_KEY "
                "(las generas en el panel de alpaca.markets, nunca las guardes en el repo)"
            )

    # ------------------------------------------------------------------- http
    def _http(self, metodo: str, ruta: str, cuerpo: dict | None = None):
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        peticion = urllib.request.Request(
            self.base + ruta, data=datos, method=metodo,
            headers={
                "APCA-API-KEY-ID": self.clave,
                "APCA-API-SECRET-KEY": self.secreto,
                "Content-Type": "application/json",
                "User-Agent": "plataforma-inversion/1.0",
            })
        try:
            with urllib.request.urlopen(peticion, timeout=self.tiempo_max) as respuesta:
                crudo = respuesta.read()
                return respuesta.status, (json.loads(crudo) if crudo else None)
        except urllib.error.HTTPError as exc:
            try:
                detalle = json.loads(exc.read())
            except (json.JSONDecodeError, ValueError):
                detalle = {"message": str(exc)}
            return exc.code, detalle
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ErrorAlpaca(f"sin conexion con Alpaca: {exc}") from exc

    def _pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
        codigo, datos = self._transporte(metodo, ruta, cuerpo)
        if codigo >= 400:
            mensaje = datos.get("message") if isinstance(datos, dict) else datos
            raise ErrorAlpaca(f"{metodo} {ruta} -> {codigo}: {mensaje}")
        return datos

    # ------------------------------------------------------------------ datos
    def cuenta(self) -> dict:
        return self._pedir("GET", "/v2/account")

    def reloj(self) -> dict:
        return self._pedir("GET", "/v2/clock")

    def posiciones(self) -> list[dict]:
        return self._pedir("GET", "/v2/positions") or []

    def orden(self, id_orden: str) -> dict:
        return self._pedir("GET", f"/v2/orders/{id_orden}")

    def orden_por_id_cliente(self, id_cliente: str) -> dict:
        consulta = urllib.parse.urlencode({"client_order_id": id_cliente})
        return self._pedir("GET", f"/v2/orders:by_client_order_id?{consulta}")

    # ---------------------------------------------------------------- ordenes
    def orden_mercado(self, simbolo: str, lado: str, notional: float | None = None,
                      cantidad: float | None = None, id_cliente: str | None = None) -> dict:
        if (notional is None) == (cantidad is None):
            raise ValueError("indica notional o cantidad, exactamente uno")
        cuerpo: dict = {"symbol": simbolo, "side": lado, "type": "market",
                        "time_in_force": "day"}
        if notional is not None:
            cuerpo["notional"] = f"{notional:.2f}"
        else:
            cuerpo["qty"] = f"{cantidad:.6f}".rstrip("0").rstrip(".")
        if id_cliente:
            cuerpo["client_order_id"] = id_cliente
        codigo, datos = self._transporte("POST", "/v2/orders", cuerpo)
        if codigo == 422 and id_cliente and "client_order_id" in str(datos):
            # el cron lanzo el ciclo dos veces: recuperar la orden original
            return self.orden_por_id_cliente(id_cliente)
        if codigo >= 400:
            mensaje = datos.get("message") if isinstance(datos, dict) else datos
            raise ErrorAlpaca(f"POST /v2/orders -> {codigo}: {mensaje}")
        return datos

    def esperar_relleno(self, id_orden: str, intentos: int = 10,
                        espera: float = 1.0) -> dict:
        orden = self.orden(id_orden)
        for _ in range(intentos):
            if orden.get("status") in ESTADOS_TERMINALES:
                break
            time.sleep(espera)
            orden = self.orden(id_orden)
        return orden


class BrokerAlpaca(BrokerBase):
    """Ejecuta las ordenes del bot contra Alpaca (paper o real).

    Si la orden queda en cola (mercado cerrado), la ejecucion devuelta usa el
    precio local como estimacion; ``bot sincronizar`` cuadra despues la
    cartera local con la del broker.
    """

    nombre = "alpaca"
    irreversible = True  # una orden real no se deshace haciendo pop() local

    def __init__(self, cliente: ClienteAlpaca, intentos_relleno: int = 10,
                 espera_relleno: float = 1.0) -> None:
        self.cliente = cliente
        self.intentos_relleno = intentos_relleno
        self.espera_relleno = espera_relleno
        self.ejecuciones: list[Ejecucion] = []

    def _ejecutar(self, simbolo: str, lado: str, unidades: float, precio: float,
                  fecha: str) -> Ejecucion:
        id_cliente = f"plataforma-{fecha}-{simbolo}-{lado}".lower()[:48]
        if lado == "buy":
            orden = self.cliente.orden_mercado(
                simbolo, "buy", notional=round(unidades * precio, 2),
                id_cliente=id_cliente)
        else:
            orden = self.cliente.orden_mercado(
                simbolo, "sell", cantidad=round(unidades, 6), id_cliente=id_cliente)
        if orden.get("status") not in ESTADOS_TERMINALES:
            orden = self.cliente.esperar_relleno(orden["id"], self.intentos_relleno,
                                                 self.espera_relleno)
        if orden.get("status") in ("canceled", "expired", "rejected"):
            raise ErrorAlpaca(f"orden {lado} {simbolo} terminada en "
                              f"'{orden.get('status')}' sin ejecutarse")
        unidades_reales = float(orden.get("filled_qty") or 0) or unidades
        precio_real = float(orden.get("filled_avg_price") or 0) or precio
        ejecucion = Ejecucion(simbolo, "COMPRA" if lado == "buy" else "VENTA",
                              unidades_reales, precio_real, 0.0, fecha)
        self.ejecuciones.append(ejecucion)
        return ejecucion

    def comprar(self, simbolo: str, unidades: float, precio: float, fecha: str) -> Ejecucion:
        return self._ejecutar(simbolo, "buy", unidades, precio, fecha)

    def vender(self, simbolo: str, unidades: float, precio: float, fecha: str) -> Ejecucion:
        return self._ejecutar(simbolo, "sell", unidades, precio, fecha)
