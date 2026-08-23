"""Optimizacion de parametros con validacion walk-forward.

Optimizar sobre todo el historico es la forma mas rapida de enganarse: siempre
aparece una combinacion que habria funcionado. Aqui los parametros se eligen en
un tramo (in-sample) y se juzgan en el siguiente, que la busqueda no ha visto
(out-of-sample). Si el resultado fuera de muestra se hunde, la estrategia esta
sobreajustada y hay que descartarla.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Mapping, Sequence

from .backtest import MotorBacktest, ResultadoBacktest
from .broker import Costes
from .estrategias import crear_estrategia
from .modelos import Barra
from .riesgo import ParametrosRiesgo

#: rejillas de busqueda por estrategia (deliberadamente pequenas: cuantas mas
#: combinaciones se prueban, mas facil es encontrar un espejismo)
REJILLAS: dict[str, dict[str, list]] = {
    "cruce_medias": {"rapida": [10, 20, 30, 50], "lenta": [50, 100, 150],
                     "filtro": [0, 200]},
    "rsi_reversion": {"periodo": [7, 14, 21], "compra": [25.0, 30.0, 35.0],
                      "venta": [55.0, 60.0, 70.0], "filtro": [0, 200]},
    "momentum": {"entrada": [20, 40, 55, 80], "salida": [10, 20, 40], "filtro": [0, 100]},
    "tendencia_ema": {"rapida": [8, 12, 20], "lenta": [21, 26, 50],
                      "umbral_atr": [0.0, 0.2, 0.5]},
    "comprar_y_mantener": {},
}


@dataclass
class Combinacion:
    parametros: dict
    metrica_dentro: float
    metrica_fuera: float
    capital_final_fuera: float
    operaciones_fuera: int

    def a_dict(self) -> dict:
        return {
            "parametros": self.parametros,
            "metrica_dentro": round(self.metrica_dentro, 4),
            "metrica_fuera": round(self.metrica_fuera, 4),
            "capital_final_fuera": round(self.capital_final_fuera, 2),
            "operaciones_fuera": self.operaciones_fuera,
        }


def _puntuar(resultado: ResultadoBacktest, metrica: str) -> float:
    m = resultado.metricas
    if metrica == "sharpe":
        return m["sharpe"]
    if metrica == "rendimiento":
        return m["rendimiento_total"]
    if metrica == "calmar":
        caida = m["maxima_caida"]
        return m["cagr"] / caida if caida > 0 else m["cagr"]
    raise ValueError(f"metrica desconocida: {metrica}")


def _partir(datos: Mapping[str, Sequence[Barra]], fraccion: float
            ) -> tuple[dict[str, list[Barra]], dict[str, list[Barra]]]:
    dentro: dict[str, list[Barra]] = {}
    fuera: dict[str, list[Barra]] = {}
    for simbolo, barras in datos.items():
        corte = int(len(barras) * fraccion)
        dentro[simbolo] = list(barras[:corte])
        fuera[simbolo] = list(barras[corte:])
    return dentro, fuera


def optimizar(nombre_estrategia: str, datos: Mapping[str, Sequence[Barra]],
              capital: float = 50.0, costes: Costes | None = None,
              riesgo: ParametrosRiesgo | None = None, metrica: str = "sharpe",
              fraccion_entrenamiento: float = 0.7, maximo: int = 200
              ) -> tuple[list[Combinacion], str]:
    """Busca parametros en el tramo de entrenamiento y los valida en el resto.

    Devuelve las combinaciones ordenadas por resultado FUERA de muestra y un
    diagnostico textual sobre el sobreajuste.
    """
    rejilla = REJILLAS.get(nombre_estrategia, {})
    dentro, fuera = _partir(datos, fraccion_entrenamiento)
    if not rejilla:
        combos: list[dict] = [{}]
    else:
        claves = list(rejilla)
        combos = [dict(zip(claves, valores)) for valores in product(*(rejilla[k] for k in claves))]
        combos = [c for c in combos if _coherente(nombre_estrategia, c)][:maximo]

    resultados: list[Combinacion] = []
    for parametros in combos:
        try:
            estrategia = crear_estrategia(nombre_estrategia, **parametros)
            r_dentro = MotorBacktest(estrategia, capital, costes, riesgo).ejecutar(dentro)
            r_fuera = MotorBacktest(crear_estrategia(nombre_estrategia, **parametros),
                                    capital, costes, riesgo).ejecutar(fuera)
        except (ValueError, ZeroDivisionError):
            continue
        if r_dentro.metricas["operaciones"] == 0:
            continue
        resultados.append(
            Combinacion(parametros, _puntuar(r_dentro, metrica), _puntuar(r_fuera, metrica),
                        r_fuera.capital_final, r_fuera.metricas["operaciones"])
        )

    if not resultados:
        return [], ("Ninguna combinacion genero operaciones. Amplia el historico "
                    "o cambia de estrategia.")

    mejor_dentro = max(resultados, key=lambda c: c.metrica_dentro)
    diagnostico = _diagnostico(mejor_dentro, resultados, metrica)
    resultados.sort(key=lambda c: c.metrica_fuera, reverse=True)
    return resultados, diagnostico


def _coherente(nombre: str, parametros: dict) -> bool:
    """Descarta combinaciones sin sentido (media rapida mas lenta que la lenta...)."""
    if nombre in ("cruce_medias", "tendencia_ema"):
        return parametros.get("rapida", 0) < parametros.get("lenta", 10**9)
    if nombre == "momentum":
        return parametros.get("salida", 0) <= parametros.get("entrada", 10**9)
    if nombre == "rsi_reversion":
        return parametros.get("compra", 0) < parametros.get("venta", 100)
    return True


def _diagnostico(mejor_dentro: Combinacion, todas: list[Combinacion], metrica: str) -> str:
    media_fuera = sum(c.metrica_fuera for c in todas) / len(todas)
    caida = mejor_dentro.metrica_dentro - mejor_dentro.metrica_fuera
    partes = [
        f"Mejor combinacion en entrenamiento: {mejor_dentro.parametros} "
        f"({metrica} {mejor_dentro.metrica_dentro:.2f})",
        f"Ese mismo juego de parametros fuera de muestra: {metrica} "
        f"{mejor_dentro.metrica_fuera:.2f} (capital {mejor_dentro.capital_final_fuera:.2f} EUR)",
        f"{metrica} medio fuera de muestra de todas las combinaciones: {media_fuera:.2f}",
    ]
    if mejor_dentro.metrica_fuera <= 0 < mejor_dentro.metrica_dentro:
        partes.append(
            "AVISO: lo que funcionaba en entrenamiento deja de funcionar fuera de "
            "muestra. Es el sintoma clasico de sobreajuste: no operes con esto."
        )
    elif caida > abs(mejor_dentro.metrica_dentro) * 0.5:
        partes.append(
            "AVISO: el resultado cae mas de la mitad fuera de muestra. Trata la "
            "mejora como ruido, no como una ventaja real."
        )
    else:
        partes.append(
            "El resultado se mantiene razonablemente fuera de muestra, lo que NO "
            "garantiza que siga funcionando en el futuro."
        )
    return "\n".join(partes)
