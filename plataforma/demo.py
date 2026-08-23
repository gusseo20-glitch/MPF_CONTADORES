#!/usr/bin/env python3
"""Demostracion completa sin conexion a internet.

    python3 demo.py

Recorre todo el flujo de la plataforma sobre datos simulados: compara
estrategias, valida parametros fuera de muestra, calcula la probabilidad real
de duplicar 50 EUR y ejecuta unos ciclos del bot automatico en papel.
"""

from __future__ import annotations

import os
import tempfile

from plataforma import montecarlo
from plataforma.backtest import MotorBacktest
from plataforma.bot import Bot
from plataforma.broker import Costes
from plataforma.config import Config
from plataforma.datos import ProveedorSintetico
from plataforma.estrategias import ESTRATEGIAS, crear_estrategia
from plataforma.optimizador import optimizar

CAPITAL = 50.0
SIMBOLOS = ["ALFA", "BETA", "GAMMA"]


def titulo(texto: str) -> None:
    print(f"\n{'=' * 76}\n {texto}\n{'=' * 76}")


def main() -> int:
    proveedor = ProveedorSintetico(semilla=101, deriva_anual=0.09, volatilidad_anual=0.28)
    datos = {s: proveedor.historico(s, 1500) for s in SIMBOLOS}
    # broker moderno de fracciones: sin comision fija, 0,05% por orden
    costes = Costes(comision_fija=0.0, comision_porcentual=0.0005, deslizamiento_pb=5.0)

    titulo("1. Comparativa de estrategias (50 EUR, broker de 0,05% por orden)")
    print(f"{'Estrategia':22s} {'Final':>9s} {'Rend.':>9s} {'Sharpe':>7s} "
          f"{'Caida':>8s} {'Ops':>5s} {'Costes':>8s}")
    resultados = {}
    for nombre in ESTRATEGIAS:
        r = MotorBacktest(crear_estrategia(nombre), CAPITAL, costes).ejecutar(datos)
        resultados[nombre] = r
        m = r.metricas
        print(f"{nombre:22s} {r.capital_final:9.2f} {m['rendimiento_total']:+8.2%} "
              f"{m['sharpe']:7.2f} {-m['maxima_caida']:8.2%} {m['operaciones']:5d} "
              f"{m['costes']:8.2f}")

    # la referencia pasiva no compite: es la vara de medir
    automaticas = {n: r for n, r in resultados.items() if n != "comprar_y_mantener"}
    mejor = max(automaticas, key=lambda n: automaticas[n].capital_final)
    referencia = resultados["comprar_y_mantener"].capital_final
    print(f"\nMejor estrategia automatica: {mejor} ({automaticas[mejor].capital_final:.2f} EUR)")
    print(f"Referencia comprar y mantener: {referencia:.2f} EUR")
    if automaticas[mejor].capital_final <= referencia:
        print("-> Ninguna estrategia automatica bate a no hacer nada en este periodo.")

    titulo("2. El peaje de la comision FIJA con una cuenta de 50 EUR")
    print("  (misma estrategia, cambiando solo lo que cobra el broker por orden)")
    for comision in (0.0, 0.5, 1.0, 3.0):
        r = MotorBacktest(crear_estrategia(mejor), CAPITAL,
                          Costes(comision_fija=comision, deslizamiento_pb=5.0)).ejecutar(datos)
        peaje = r.metricas["costes"] / CAPITAL
        print(f"  comision {comision:4.2f} EUR/orden -> capital final {r.capital_final:7.2f} EUR "
              f"| costes {r.metricas['costes']:6.2f} EUR ({peaje:5.1%} del capital)")

    titulo("3. Validacion fuera de muestra (deteccion de sobreajuste)")
    _, diagnostico = optimizar(mejor, datos, CAPITAL, costes)
    print(diagnostico)

    titulo("4. Probabilidad REAL de convertir 50 EUR en 100 EUR")
    r = resultados[mejor]
    if r.operaciones:
        for horizonte in (25, 100, 400):
            mc = montecarlo.desde_operaciones(r.operaciones, CAPITAL, horizonte=horizonte,
                                              simulaciones=8000)
            print(f"  {horizonte:4d} operaciones -> P(duplicar) {mc.prob_objetivo:6.1%} | "
                  f"P(perder) {mc.prob_perdida:6.1%} | P(ruina) {mc.prob_ruina:6.1%} | "
                  f"mediana {mc.mediana:7.2f} EUR")
    else:
        print("  La mejor estrategia no genero operaciones en este periodo.")

    titulo("5. Bot automatico en papel (3 ciclos)")
    with tempfile.TemporaryDirectory() as tmp:
        config = Config(capital=CAPITAL, simbolos=SIMBOLOS, proveedor="sintetico",
                        estrategia=mejor, dias=1500, costes=costes.a_dict())
        bot = Bot(config, ruta_estado=os.path.join(tmp, "estado.json"))
        bot.reiniciar()
        for ciclo in range(1, 4):
            resultado = bot.ejecutar_ciclo()
            print(f"  ciclo {ciclo}: cartera {resultado['valor_cartera']:.2f} EUR "
                  f"({resultado['rendimiento']:+.2%}), {resultado['posiciones']} posiciones")
            for accion in resultado["acciones"]:
                simbolo = f"[{accion['simbolo']}] " if accion["simbolo"] else ""
                print(f"      {accion['tipo']:12s} {simbolo}{accion['mensaje']}")

    titulo("Conclusion")
    print("Los datos de esta demostracion son SIMULADOS. Con datos reales cambian los\n"
          "numeros, pero no las tres conclusiones: los costes pesan muchisimo en una\n"
          "cuenta de 50 EUR, lo que funciona en el pasado se degrada fuera de muestra, y\n"
          "duplicar el capital es una probabilidad, nunca una promesa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
