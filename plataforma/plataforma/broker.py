"""Brokers: ejecucion simulada (papel) e interfaz para brokers reales.

La plataforma opera SIEMPRE contra esta interfaz. El broker de papel aplica
comisiones y deslizamiento realistas, porque con 50 EUR de capital los costes
son el factor que decide si una estrategia gana o pierde.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Costes:
    """Modelo de costes de un broker.

    Valores por defecto: broker europeo tipo "1 EUR por orden" (Trade Republic,
    DEGIRO...). Ajustalo al tuyo antes de fiarte de ningun backtest.
    """

    comision_fija: float = 1.0        # EUR por orden
    comision_porcentual: float = 0.0  # p.ej. 0.0005 = 0,05%
    comision_minima: float = 0.0
    deslizamiento_pb: float = 5.0     # puntos basicos sobre el precio (5 pb = 0,05%)
    tasa_operaciones: float = 0.0     # p.ej. 0.002 en compras de acciones espanolas

    def comision(self, importe: float, es_compra: bool) -> float:
        coste = self.comision_fija + importe * self.comision_porcentual
        coste = max(coste, self.comision_minima)
        if es_compra:
            coste += importe * self.tasa_operaciones
        return coste

    def precio_ejecucion(self, precio: float, es_compra: bool) -> float:
        desliz = precio * (self.deslizamiento_pb / 10_000.0)
        return precio + desliz if es_compra else precio - desliz

    def a_dict(self) -> dict:
        return asdict(self)


def unidades_asequibles(costes: Costes, efectivo: float, precio: float,
                        unidades: float) -> float:
    """Recorta las unidades para que la orden quepa en el efectivo disponible.

    Sin este ajuste, el deslizamiento y la comision pueden dejar una orden
    perfectamente razonable un centimo por encima del saldo, y se perderia la
    operacion entera por redondeo.
    """
    if unidades <= 0 or precio <= 0 or efectivo <= 0:
        return 0.0
    real = costes.precio_ejecucion(precio, True)
    coste = unidades * real + costes.comision(unidades * real, True)
    if coste <= efectivo:
        return unidades
    disponible = efectivo - costes.comision(efectivo, True)
    if disponible <= 0:
        return 0.0
    return max(0.0, disponible / real * 0.999)


SIN_COSTES = Costes(comision_fija=0.0, comision_porcentual=0.0, deslizamiento_pb=0.0)


@dataclass
class Ejecucion:
    simbolo: str
    lado: str  # COMPRA | VENTA
    unidades: float
    precio: float
    comision: float
    fecha: str

    @property
    def importe(self) -> float:
        return self.unidades * self.precio

    @property
    def efectivo(self) -> float:
        """Variacion de efectivo (negativa en compras)."""
        if self.lado == "COMPRA":
            return -(self.importe + self.comision)
        return self.importe - self.comision

    def a_dict(self) -> dict:
        d = asdict(self)
        d["importe"] = round(self.importe, 2)
        return d


class BrokerBase:
    nombre = "base"
    #: True si las ordenes no se pueden deshacer localmente (broker de verdad)
    irreversible = False

    def comprar(self, simbolo: str, unidades: float, precio: float, fecha: str) -> Ejecucion:
        raise NotImplementedError

    def vender(self, simbolo: str, unidades: float, precio: float, fecha: str) -> Ejecucion:
        raise NotImplementedError


class BrokerPapel(BrokerBase):
    """Ejecucion simulada: aplica deslizamiento y comisiones, sin dinero real."""

    nombre = "papel"

    def __init__(self, costes: Costes | None = None) -> None:
        self.costes = costes or Costes()
        self.ejecuciones: list[Ejecucion] = []

    def comprar(self, simbolo: str, unidades: float, precio: float, fecha: str) -> Ejecucion:
        real = self.costes.precio_ejecucion(precio, True)
        eje = Ejecucion(simbolo, "COMPRA", unidades, real,
                        self.costes.comision(unidades * real, True), fecha)
        self.ejecuciones.append(eje)
        return eje

    def vender(self, simbolo: str, unidades: float, precio: float, fecha: str) -> Ejecucion:
        real = self.costes.precio_ejecucion(precio, False)
        eje = Ejecucion(simbolo, "VENTA", unidades, real,
                        self.costes.comision(unidades * real, False), fecha)
        self.ejecuciones.append(eje)
        return eje


class BrokerReal(BrokerBase):
    """La conexion real esta en `plataforma.alpaca.BrokerAlpaca`.

    Se llega a ella por configuracion (modo `alpaca_papel` o `alpaca_real`),
    con credenciales por variables de entorno y, para dinero real, la
    confirmacion explicita PLATAFORMA_DINERO_REAL=acepto.
    """

    nombre = "real"

    def __init__(self, *_, **__) -> None:
        raise NotImplementedError(
            "Usa el modo 'alpaca_papel' o 'alpaca_real' en la configuracion: la "
            "conexion real vive en plataforma.alpaca.BrokerAlpaca."
        )
