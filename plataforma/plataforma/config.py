"""Configuracion de la plataforma (fichero JSON + valores por defecto)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

from .broker import Costes
from .riesgo import ParametrosRiesgo

RUTA_POR_DEFECTO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


@dataclass
class Config:
    #: capital de partida en EUR
    capital: float = 50.0
    #: activos sobre los que operar
    simbolos: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "AAPL", "MSFT"])
    #: estrategia y sus parametros
    estrategia: str = "cruce_medias"
    parametros_estrategia: dict = field(default_factory=dict)
    #: proveedor de datos: auto | yahoo | stooq | csv | sintetico
    proveedor: str = "auto"
    #: sesiones de historico que se descargan
    dias: int = 750
    #: modo de operacion:
    #:   papel        simulador local (por defecto)
    #:   alpaca_papel cuenta de practica de Alpaca (misma API, sin dinero real)
    #:   alpaca_real  dinero real; exige PLATAFORMA_DINERO_REAL=acepto
    modo: str = "papel"
    costes: dict = field(default_factory=lambda: asdict(Costes()))
    riesgo: dict = field(default_factory=lambda: asdict(ParametrosRiesgo()))
    #: fichero donde el bot guarda su estado entre ejecuciones
    estado: str = "estado_bot.json"

    def objeto_costes(self) -> Costes:
        return Costes(**self.costes)

    def objeto_riesgo(self) -> ParametrosRiesgo:
        return ParametrosRiesgo(**self.riesgo)

    def a_dict(self) -> dict:
        return asdict(self)

    def guardar(self, ruta: str = RUTA_POR_DEFECTO) -> str:
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(self.a_dict(), fh, indent=2, ensure_ascii=False)
        return ruta

    @classmethod
    def cargar(cls, ruta: str = RUTA_POR_DEFECTO) -> "Config":
        if not os.path.exists(ruta):
            return cls()
        with open(ruta, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
        validos = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in datos.items() if k in validos})
