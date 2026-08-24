"""Modelos de datos basicos de la plataforma."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Iterable


@dataclass(frozen=True)
class Barra:
    """Una vela OHLCV de un activo."""

    fecha: str
    apertura: float
    maximo: float
    minimo: float
    cierre: float
    volumen: float = 0.0

    @property
    def rango(self) -> float:
        return self.maximo - self.minimo

    @classmethod
    def desde_dict(cls, d: dict) -> "Barra":
        return cls(
            fecha=str(d["fecha"]),
            apertura=float(d["apertura"]),
            maximo=float(d["maximo"]),
            minimo=float(d["minimo"]),
            cierre=float(d["cierre"]),
            volumen=float(d.get("volumen", 0.0) or 0.0),
        )

    def a_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Senal:
    """Decision de una estrategia para una barra concreta."""

    accion: str  # COMPRAR | VENDER | MANTENER
    fuerza: float = 0.0  # 0..1, confianza relativa de la senal
    motivo: str = ""

    def __post_init__(self) -> None:
        if self.accion not in ("COMPRAR", "VENDER", "MANTENER"):
            raise ValueError(f"accion no valida: {self.accion}")


MANTENER = Senal("MANTENER")


@dataclass
class Posicion:
    """Posicion abierta sobre un activo (solo largos)."""

    simbolo: str
    unidades: float
    precio_entrada: float
    fecha_entrada: str
    stop: float | None = None
    stop_inicial: float | None = None
    objetivo: float | None = None
    maximo_favorable: float = 0.0
    comision_entrada: float = 0.0
    capital_antes: float = 0.0

    def valor(self, precio: float) -> float:
        return self.unidades * precio

    def pl_abierto(self, precio: float) -> float:
        return (precio - self.precio_entrada) * self.unidades


@dataclass
class Operacion:
    """Operacion cerrada (round trip) con su resultado."""

    simbolo: str
    fecha_entrada: str
    fecha_salida: str
    precio_entrada: float
    precio_salida: float
    unidades: float
    comisiones: float
    motivo_salida: str
    capital_antes: float

    @property
    def beneficio(self) -> float:
        bruto = (self.precio_salida - self.precio_entrada) * self.unidades
        return bruto - self.comisiones

    @property
    def rendimiento(self) -> float:
        """Rendimiento sobre el capital total en el momento de abrir."""
        if self.capital_antes <= 0:
            return 0.0
        return self.beneficio / self.capital_antes

    @property
    def ganadora(self) -> bool:
        return self.beneficio > 0

    def a_dict(self) -> dict:
        d = asdict(self)
        d["beneficio"] = round(self.beneficio, 4)
        d["rendimiento"] = round(self.rendimiento, 6)
        return d


@dataclass
class Cartera:
    """Estado de la cartera: efectivo, posiciones e historico."""

    efectivo: float
    posiciones: dict[str, Posicion] = field(default_factory=dict)
    operaciones: list[Operacion] = field(default_factory=list)
    curva: list[tuple[str, float]] = field(default_factory=list)

    def valor_total(self, precios: dict[str, float]) -> float:
        total = self.efectivo
        for simbolo, pos in self.posiciones.items():
            total += pos.valor(precios.get(simbolo, pos.precio_entrada))
        return total

    def registrar(self, fecha: str, precios: dict[str, float]) -> float:
        valor = self.valor_total(precios)
        self.curva.append((fecha, valor))
        return valor

    def a_dict(self, precios: dict[str, float] | None = None) -> dict:
        precios = precios or {}
        return {
            "efectivo": round(self.efectivo, 2),
            "valor_total": round(self.valor_total(precios), 2),
            "posiciones": [
                {
                    "simbolo": p.simbolo,
                    "unidades": round(p.unidades, 6),
                    "precio_entrada": round(p.precio_entrada, 4),
                    "fecha_entrada": p.fecha_entrada,
                    "stop": round(p.stop, 4) if p.stop else None,
                    "objetivo": round(p.objetivo, 4) if p.objetivo else None,
                    "precio_actual": round(precios.get(p.simbolo, p.precio_entrada), 4),
                    "pl_abierto": round(
                        p.pl_abierto(precios.get(p.simbolo, p.precio_entrada)), 2
                    ),
                }
                for p in self.posiciones.values()
            ],
            "operaciones": [o.a_dict() for o in self.operaciones],
        }


def serie_a_json(barras: Iterable[Barra]) -> str:
    return json.dumps([b.a_dict() for b in barras], ensure_ascii=False)
