"""Indicadores tecnicos y metricas estadisticas (solo stdlib)."""

from __future__ import annotations

import math
from typing import Sequence

from .modelos import Barra

DIAS_HABILES_ANIO = 252


def cierres(barras: Sequence[Barra]) -> list[float]:
    return [b.cierre for b in barras]


def sma(valores: Sequence[float], periodo: int) -> float | None:
    """Media movil simple del ultimo tramo."""
    if periodo <= 0 or len(valores) < periodo:
        return None
    return sum(valores[-periodo:]) / periodo


def serie_sma(valores: Sequence[float], periodo: int) -> list[float | None]:
    salida: list[float | None] = []
    acumulado = 0.0
    for i, v in enumerate(valores):
        acumulado += v
        if i >= periodo:
            acumulado -= valores[i - periodo]
        salida.append(acumulado / periodo if i >= periodo - 1 else None)
    return salida


def ema(valores: Sequence[float], periodo: int) -> float | None:
    if periodo <= 0 or len(valores) < periodo:
        return None
    k = 2.0 / (periodo + 1.0)
    media = sum(valores[:periodo]) / periodo
    for v in valores[periodo:]:
        media = v * k + media * (1 - k)
    return media


def rsi(valores: Sequence[float], periodo: int = 14) -> float | None:
    """RSI de Wilder. Devuelve None si no hay datos suficientes."""
    if periodo <= 0 or len(valores) < periodo + 1:
        return None
    ganancias = 0.0
    perdidas = 0.0
    for i in range(1, periodo + 1):
        cambio = valores[i] - valores[i - 1]
        if cambio >= 0:
            ganancias += cambio
        else:
            perdidas -= cambio
    media_g = ganancias / periodo
    media_p = perdidas / periodo
    for i in range(periodo + 1, len(valores)):
        cambio = valores[i] - valores[i - 1]
        g = max(cambio, 0.0)
        p = max(-cambio, 0.0)
        media_g = (media_g * (periodo - 1) + g) / periodo
        media_p = (media_p * (periodo - 1) + p) / periodo
    if media_p == 0:
        return 100.0
    rs = media_g / media_p
    return 100.0 - (100.0 / (1.0 + rs))


def atr(barras: Sequence[Barra], periodo: int = 14) -> float | None:
    """Average True Range (Wilder)."""
    if len(barras) < periodo + 1:
        return None
    rangos: list[float] = []
    for i in range(1, len(barras)):
        b = barras[i]
        cierre_previo = barras[i - 1].cierre
        rangos.append(
            max(
                b.maximo - b.minimo,
                abs(b.maximo - cierre_previo),
                abs(b.minimo - cierre_previo),
            )
        )
    media = sum(rangos[:periodo]) / periodo
    for r in rangos[periodo:]:
        media = (media * (periodo - 1) + r) / periodo
    return media


def rendimientos(valores: Sequence[float]) -> list[float]:
    salida = []
    for i in range(1, len(valores)):
        previo = valores[i - 1]
        if previo > 0:
            salida.append(valores[i] / previo - 1.0)
    return salida


def desviacion(valores: Sequence[float]) -> float:
    n = len(valores)
    if n < 2:
        return 0.0
    media = sum(valores) / n
    var = sum((v - media) ** 2 for v in valores) / (n - 1)
    return math.sqrt(var)


def volatilidad_anual(valores: Sequence[float]) -> float:
    """Volatilidad anualizada a partir de una serie de precios."""
    return desviacion(rendimientos(valores)) * math.sqrt(DIAS_HABILES_ANIO)


def sharpe(rends: Sequence[float], tasa_libre_riesgo: float = 0.0) -> float:
    if len(rends) < 2:
        return 0.0
    diaria = tasa_libre_riesgo / DIAS_HABILES_ANIO
    exceso = [r - diaria for r in rends]
    sd = desviacion(exceso)
    if sd == 0:
        return 0.0
    media = sum(exceso) / len(exceso)
    return (media / sd) * math.sqrt(DIAS_HABILES_ANIO)


def sortino(rends: Sequence[float], tasa_libre_riesgo: float = 0.0) -> float:
    if len(rends) < 2:
        return 0.0
    diaria = tasa_libre_riesgo / DIAS_HABILES_ANIO
    exceso = [r - diaria for r in rends]
    negativos = [e for e in exceso if e < 0]
    if not negativos:
        return 0.0
    downside = math.sqrt(sum(e * e for e in negativos) / len(exceso))
    if downside == 0:
        return 0.0
    media = sum(exceso) / len(exceso)
    return (media / downside) * math.sqrt(DIAS_HABILES_ANIO)


def maxima_caida(valores: Sequence[float]) -> float:
    """Maximum drawdown en tanto por uno (positivo, p.ej. 0.32 = -32%)."""
    if not valores:
        return 0.0
    pico = valores[0]
    peor = 0.0
    for v in valores:
        if v > pico:
            pico = v
        if pico > 0:
            caida = (pico - v) / pico
            if caida > peor:
                peor = caida
    return peor


def percentil(valores: Sequence[float], p: float) -> float:
    """Percentil p (0..100) por interpolacion lineal."""
    if not valores:
        return 0.0
    orden = sorted(valores)
    if len(orden) == 1:
        return orden[0]
    pos = (len(orden) - 1) * (p / 100.0)
    bajo = math.floor(pos)
    alto = math.ceil(pos)
    if bajo == alto:
        return orden[int(pos)]
    return orden[bajo] + (orden[alto] - orden[bajo]) * (pos - bajo)
