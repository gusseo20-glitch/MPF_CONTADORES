"""Gestion de riesgo: tamano de posicion, stops y cortacircuitos.

Con un capital pequeno (50 EUR) la gestion de riesgo no es un adorno: es lo
unico que separa "sigo en juego" de "me he quedado a cero". Las reglas aqui
son deliberadamente conservadoras y todas se pueden ajustar por configuracion.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

from .indicadores import atr
from .modelos import Barra, Posicion


@dataclass
class ParametrosRiesgo:
    #: fraccion maxima del capital total que puede ir a una sola posicion
    fraccion_maxima: float = 0.5
    #: fraccion del capital que se acepta perder si salta el stop (regla del 2%)
    riesgo_por_operacion: float = 0.02
    #: distancia del stop en multiplos de ATR
    multiplo_stop_atr: float = 2.0
    #: objetivo de beneficio en multiplos del riesgo asumido (R). 0 = sin objetivo
    multiplo_objetivo_r: float = 3.0
    #: activa stop dinamico que sube con el precio
    stop_dinamico: bool = True
    #: el stop dinamico no empieza a seguir al precio hasta ganar este multiplo
    #: del riesgo inicial (R). Evita que un avance minimo cierre la operacion.
    dinamico_tras_r: float = 1.0
    #: caida maxima de la cartera antes de detener la operativa (cortacircuitos)
    caida_maxima: float = 0.25
    #: sesiones de pausa tras saltar el cortacircuitos (0 = parada definitiva)
    sesiones_pausa: int = 20
    #: importe minimo por operacion; por debajo, las comisiones se comen todo
    importe_minimo: float = 10.0
    #: numero maximo de posiciones abiertas a la vez
    posiciones_maximas: int = 3
    #: permitir fracciones de accion (brokers tipo Trade Republic / IBKR)
    fracciones: bool = True
    #: periodo del ATR usado para stops y tamano
    periodo_atr: int = 14

    def a_dict(self) -> dict:
        return asdict(self)


class GestorRiesgo:
    """Calcula cuanto comprar, donde poner el stop y cuando parar del todo."""

    def __init__(self, parametros: ParametrosRiesgo | None = None) -> None:
        self.p = parametros or ParametrosRiesgo()
        self.pico_capital = 0.0
        self.detenido = False
        self.motivo_detencion = ""
        self.pausa_restante = 0

    # ------------------------------------------------------------------ stops
    def calcular_stop(self, barras: Sequence[Barra], precio: float) -> float:
        """Stop por volatilidad (ATR). Si no hay ATR, usa un 8% fijo."""
        rango = atr(barras, self.p.periodo_atr)
        if not rango or rango <= 0:
            return precio * 0.92
        stop = precio - rango * self.p.multiplo_stop_atr
        return max(stop, precio * 0.5)  # nunca un stop absurdamente lejano

    def calcular_objetivo(self, precio: float, stop: float) -> float | None:
        if self.p.multiplo_objetivo_r <= 0:
            return None
        riesgo = precio - stop
        if riesgo <= 0:
            return None
        return precio + riesgo * self.p.multiplo_objetivo_r

    def actualizar_stop_dinamico(self, posicion: Posicion, barra: Barra,
                                 barras: Sequence[Barra]) -> None:
        """Sube el stop cuando el precio avanza a favor. Nunca lo baja."""
        if not self.p.stop_dinamico or posicion.stop is None:
            return
        posicion.maximo_favorable = max(posicion.maximo_favorable, barra.maximo)
        referencia = posicion.stop_inicial if posicion.stop_inicial is not None else posicion.stop
        riesgo_inicial = posicion.precio_entrada - referencia
        if riesgo_inicial > 0 and self.p.dinamico_tras_r > 0:
            umbral = posicion.precio_entrada + riesgo_inicial * self.p.dinamico_tras_r
            if posicion.maximo_favorable < umbral:
                return  # todavia no hay beneficio suficiente para mover el stop
        rango = atr(barras, self.p.periodo_atr)
        if not rango or rango <= 0:
            return
        candidato = posicion.maximo_favorable - rango * self.p.multiplo_stop_atr
        if candidato > posicion.stop:
            posicion.stop = candidato

    # ---------------------------------------------------------------- tamanos
    def unidades(self, capital_total: float, efectivo: float, precio: float,
                 stop: float, fuerza: float = 1.0) -> float:
        """Unidades a comprar segun riesgo, limite de concentracion y efectivo.

        Devuelve 0 si la operacion no llega al importe minimo razonable.
        """
        if precio <= 0 or capital_total <= 0 or efectivo <= 0:
            return 0.0

        riesgo_unidad = max(precio - stop, precio * 0.01)
        presupuesto_riesgo = capital_total * self.p.riesgo_por_operacion
        por_riesgo = presupuesto_riesgo / riesgo_unidad

        # nunca mas de `fraccion_maxima` del capital en una sola posicion,
        # escalado por la confianza de la senal
        tope_importe = capital_total * self.p.fraccion_maxima * max(0.0, min(1.0, fuerza))
        por_concentracion = tope_importe / precio

        por_efectivo = efectivo / precio

        unidades = min(por_riesgo, por_concentracion, por_efectivo)
        if not self.p.fracciones:
            unidades = float(int(unidades))
        else:
            unidades = round(unidades, 6)

        if unidades <= 0 or unidades * precio < self.p.importe_minimo:
            return 0.0
        return unidades

    def puede_abrir(self, abiertas: int) -> bool:
        return not self.detenido and abiertas < self.p.posiciones_maximas

    # --------------------------------------------------------- cortacircuitos
    def revisar_cortacircuitos(self, capital_total: float) -> bool:
        """Detiene la operativa si la cartera cae mas de `caida_maxima`.

        Devuelve True si a partir de ahora hay que dejar de abrir posiciones.
        """
        if self.detenido and self.p.sesiones_pausa > 0:
            self.pausa_restante -= 1
            if self.pausa_restante <= 0:
                # se reanuda con el maximo puesto a cero: el listen de la pausa
                # es dejar de operar mientras dura el mal momento, no jubilarse
                self.detenido = False
                self.motivo_detencion = ""
                self.pico_capital = capital_total
            return self.detenido

        self.pico_capital = max(self.pico_capital, capital_total)
        if self.pico_capital <= 0:
            return self.detenido
        caida = (self.pico_capital - capital_total) / self.pico_capital
        if caida >= self.p.caida_maxima and not self.detenido:
            self.detenido = True
            self.pausa_restante = self.p.sesiones_pausa
            pausa = (f", pausa de {self.p.sesiones_pausa} sesiones"
                     if self.p.sesiones_pausa > 0 else ", parada definitiva")
            self.motivo_detencion = (
                f"caida del {caida:.1%} sobre el maximo "
                f"(limite {self.p.caida_maxima:.0%}){pausa}"
            )
        return self.detenido

    def salida_forzosa(self, posicion: Posicion, barra: Barra) -> tuple[bool, float, str]:
        """Comprueba si la barra toca el stop o el objetivo.

        Devuelve (hay_salida, precio_ejecucion, motivo). Si en la misma barra se
        tocan stop y objetivo se asume el peor caso (stop), que es la hipotesis
        prudente al no conocer el orden intradia.
        """
        if posicion.stop is not None and barra.minimo <= posicion.stop:
            precio = min(posicion.stop, barra.apertura)  # hueco a la baja
            return True, precio, "stop"
        if posicion.objetivo is not None and barra.maximo >= posicion.objetivo:
            precio = max(posicion.objetivo, barra.apertura)
            return True, precio, "objetivo"
        return False, 0.0, ""
