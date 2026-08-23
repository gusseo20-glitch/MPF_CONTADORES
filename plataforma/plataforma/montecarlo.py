"""Simulacion Monte Carlo: que probabilidad REAL hay de duplicar el capital.

Un backtest da un unico camino: el que ocurrio. Reordenando al azar los
resultados de las operaciones (bootstrap) se obtienen miles de caminos
igual de verosimiles y, con ellos, la distribucion de resultados posibles.

Esa distribucion es la respuesta honesta a "puedo duplicar 50 EUR": no un si
o un no, sino una probabilidad, junto a la probabilidad de arruinarse.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from .indicadores import percentil
from .modelos import Operacion


@dataclass
class ResultadoMonteCarlo:
    simulaciones: int
    horizonte: int
    capital_inicial: float
    objetivo: float
    prob_objetivo: float
    prob_perdida: float
    prob_ruina: float
    mediana: float
    media: float
    p5: float
    p25: float
    p75: float
    p95: float
    peor: float
    mejor: float
    caida_media: float
    metodo: str

    def a_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}

    def resumen(self) -> str:
        objetivo_eur = self.capital_inicial * self.objetivo
        return "\n".join([
            f"Simulaciones      : {self.simulaciones:,} caminos ({self.metodo}, "
            f"horizonte {self.horizonte})",
            f"Capital inicial   : {self.capital_inicial:,.2f} EUR",
            "",
            f"P(llegar a {objetivo_eur:,.0f} EUR)  : {self.prob_objetivo:.1%}   <-- probabilidad de duplicar",
            f"P(acabar perdiendo)   : {self.prob_perdida:.1%}",
            f"P(ruina, -80% o mas)  : {self.prob_ruina:.1%}",
            "",
            f"Resultado mediano : {self.mediana:,.2f} EUR",
            f"Resultado medio   : {self.media:,.2f} EUR",
            f"Rango 5%-95%      : {self.p5:,.2f} - {self.p95:,.2f} EUR",
            f"Rango 25%-75%     : {self.p25:,.2f} - {self.p75:,.2f} EUR",
            f"Peor / mejor caso : {self.peor:,.2f} / {self.mejor:,.2f} EUR",
            f"Caida media maxima: -{self.caida_media:.1%}",
        ])


def simular(rendimientos_muestra: Sequence[float], capital_inicial: float = 50.0,
            horizonte: int = 100, simulaciones: int = 10_000, objetivo: float = 2.0,
            semilla: int = 42, metodo: str = "operaciones",
            umbral_ruina: float = 0.2) -> ResultadoMonteCarlo:
    """Bootstrap sobre una muestra de rendimientos (por operacion o diarios).

    `objetivo` es el multiplicador buscado (2.0 = duplicar). Se cuenta como
    exito tocar el objetivo en cualquier momento del camino, no solo al final.
    """
    if not rendimientos_muestra:
        raise ValueError("no hay rendimientos con los que simular")

    rng = random.Random(semilla)
    finales: list[float] = []
    caidas: list[float] = []
    exitos = 0
    perdidas = 0
    ruinas = 0
    meta = capital_inicial * objetivo
    suelo = capital_inicial * umbral_ruina

    for _ in range(simulaciones):
        capital = capital_inicial
        pico = capital
        peor_caida = 0.0
        toco_objetivo = False
        toco_ruina = False
        for _ in range(horizonte):
            capital *= 1.0 + rng.choice(rendimientos_muestra)
            if capital <= 0:
                capital = 0.0
                toco_ruina = True
                break
            pico = max(pico, capital)
            peor_caida = max(peor_caida, (pico - capital) / pico if pico > 0 else 0.0)
            if capital >= meta:
                toco_objetivo = True
            if capital <= suelo:
                toco_ruina = True
                break
        finales.append(capital)
        caidas.append(peor_caida)
        exitos += 1 if toco_objetivo else 0
        perdidas += 1 if capital < capital_inicial else 0
        ruinas += 1 if toco_ruina else 0

    return ResultadoMonteCarlo(
        simulaciones=simulaciones,
        horizonte=horizonte,
        capital_inicial=capital_inicial,
        objetivo=objetivo,
        prob_objetivo=exitos / simulaciones,
        prob_perdida=perdidas / simulaciones,
        prob_ruina=ruinas / simulaciones,
        mediana=percentil(finales, 50),
        media=sum(finales) / len(finales),
        p5=percentil(finales, 5),
        p25=percentil(finales, 25),
        p75=percentil(finales, 75),
        p95=percentil(finales, 95),
        peor=min(finales),
        mejor=max(finales),
        caida_media=sum(caidas) / len(caidas),
        metodo=metodo,
    )


def desde_operaciones(operaciones: Sequence[Operacion], capital_inicial: float = 50.0,
                      horizonte: int | None = None, **kwargs) -> ResultadoMonteCarlo:
    """Monte Carlo reordenando los resultados de las operaciones del backtest."""
    muestra = [o.rendimiento for o in operaciones]
    if not muestra:
        raise ValueError(
            "el backtest no genero operaciones: no hay nada que simular. "
            "Prueba otra estrategia, otro activo o un periodo mas largo."
        )
    return simular(muestra, capital_inicial,
                   horizonte if horizonte is not None else max(len(muestra), 20),
                   metodo="operaciones", **kwargs)


def desde_curva(curva: Sequence[tuple[str, float]], capital_inicial: float = 50.0,
                horizonte: int = 252, **kwargs) -> ResultadoMonteCarlo:
    """Monte Carlo reordenando los rendimientos DIARIOS de la curva de capital."""
    valores = [v for _, v in curva]
    muestra = [valores[i] / valores[i - 1] - 1.0
               for i in range(1, len(valores)) if valores[i - 1] > 0]
    muestra = [r for r in muestra if r != 0.0] or muestra
    if not muestra:
        raise ValueError("la curva de capital no tiene variaciones que simular")
    return simular(muestra, capital_inicial, horizonte, metodo="diario", **kwargs)


def operaciones_necesarias(rendimiento_medio: float, objetivo: float = 2.0) -> float:
    """Cuantas operaciones ganadoras medias hacen falta para llegar al objetivo."""
    import math
    if rendimiento_medio <= 0:
        return float("inf")
    return math.log(objetivo) / math.log(1 + rendimiento_medio)
