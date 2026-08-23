"""Motor de backtest y metricas.

Reglas del motor (importantes para que los resultados no sean humo):

* Las senales se calculan con el cierre de la barra `t` y se ejecutan en la
  apertura de la barra `t+1`. Nunca se opera con informacion del futuro.
* Los stops y objetivos se comprueban con el maximo/minimo de cada barra y,
  si en la misma barra se tocan los dos, se asume que salto el stop.
* Toda ejecucion pasa por el broker, con comisiones y deslizamiento.
* Al final del periodo se liquidan las posiciones abiertas al ultimo cierre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .broker import BrokerPapel, Costes, unidades_asequibles
from .estrategias import Estrategia
from .indicadores import (DIAS_HABILES_ANIO, maxima_caida, rendimientos, sharpe,
                          sortino, volatilidad_anual)
from .modelos import Barra, Cartera, Operacion, Posicion
from .riesgo import GestorRiesgo, ParametrosRiesgo


@dataclass
class OrdenPendiente:
    simbolo: str
    lado: str  # COMPRA | VENTA
    fuerza: float
    motivo: str


@dataclass
class ResultadoBacktest:
    capital_inicial: float
    capital_final: float
    curva: list[tuple[str, float]]
    operaciones: list[Operacion]
    metricas: dict
    avisos: list[str] = field(default_factory=list)
    cartera: Cartera | None = None

    def a_dict(self) -> dict:
        return {
            "capital_inicial": round(self.capital_inicial, 2),
            "capital_final": round(self.capital_final, 2),
            "curva": [[f, round(v, 4)] for f, v in self.curva],
            "operaciones": [o.a_dict() for o in self.operaciones],
            "metricas": self.metricas,
            "avisos": self.avisos,
        }

    def resumen(self) -> str:
        m = self.metricas
        lineas = [
            f"Capital inicial : {self.capital_inicial:,.2f} EUR",
            f"Capital final   : {self.capital_final:,.2f} EUR",
            f"Rendimiento     : {m['rendimiento_total']:+.2%}",
            f"CAGR            : {m['cagr']:+.2%}",
            f"Volatilidad     : {m['volatilidad']:.2%}",
            f"Sharpe          : {m['sharpe']:.2f}",
            f"Sortino         : {m['sortino']:.2f}",
            f"Maxima caida    : -{m['maxima_caida']:.2%}",
            f"Operaciones     : {m['operaciones']} ({m['acierto']:.1%} aciertos)",
            f"Factor beneficio: {m['factor_beneficio']:.2f}",
            f"Ganancia media  : {m['ganancia_media']:+.2f} EUR",
            f"Perdida media   : {m['perdida_media']:+.2f} EUR",
            f"Costes totales  : {m['costes']:.2f} EUR",
        ]
        return "\n".join(lineas)


def calcular_metricas(curva: Sequence[tuple[str, float]], operaciones: Sequence[Operacion],
                      capital_inicial: float) -> dict:
    valores = [v for _, v in curva]
    final = valores[-1] if valores else capital_inicial
    rends = rendimientos(valores)
    anios = max(len(valores) / DIAS_HABILES_ANIO, 1e-9)
    if capital_inicial > 0 and final > 0:
        cagr = (final / capital_inicial) ** (1 / anios) - 1
    else:
        cagr = -1.0
    ganadoras = [o for o in operaciones if o.ganadora]
    perdedoras = [o for o in operaciones if not o.ganadora]
    beneficio_bruto = sum(o.beneficio for o in ganadoras)
    perdida_bruta = abs(sum(o.beneficio for o in perdedoras))
    return {
        "rendimiento_total": (final / capital_inicial - 1) if capital_inicial else 0.0,
        "cagr": cagr,
        "volatilidad": volatilidad_anual(valores),
        "sharpe": sharpe(rends),
        "sortino": sortino(rends),
        "maxima_caida": maxima_caida(valores),
        "operaciones": len(operaciones),
        "acierto": (len(ganadoras) / len(operaciones)) if operaciones else 0.0,
        "factor_beneficio": (beneficio_bruto / perdida_bruta) if perdida_bruta > 0
        else (float("inf") if beneficio_bruto > 0 else 0.0),
        "ganancia_media": (beneficio_bruto / len(ganadoras)) if ganadoras else 0.0,
        "perdida_media": (-perdida_bruta / len(perdedoras)) if perdedoras else 0.0,
        "esperanza": (sum(o.beneficio for o in operaciones) / len(operaciones))
        if operaciones else 0.0,
        "costes": sum(o.comisiones for o in operaciones),
        "dias": len(valores),
    }


class MotorBacktest:
    def __init__(self, estrategia: Estrategia, capital: float = 50.0,
                 costes: Costes | None = None,
                 riesgo: ParametrosRiesgo | None = None) -> None:
        self.estrategia = estrategia
        self.capital = capital
        self.costes = costes or Costes()
        self.parametros_riesgo = riesgo or ParametrosRiesgo()

    def ejecutar(self, datos: Mapping[str, Sequence[Barra]]) -> ResultadoBacktest:
        if not datos:
            raise ValueError("no hay datos para el backtest")

        broker = BrokerPapel(self.costes)
        gestor = GestorRiesgo(self.parametros_riesgo)
        cartera = Cartera(efectivo=self.capital)
        avisos: list[str] = []

        indices: dict[str, dict[str, int]] = {
            s: {b.fecha: i for i, b in enumerate(barras)} for s, barras in datos.items()
        }
        fechas = sorted({b.fecha for barras in datos.values() for b in barras})
        pendientes: list[OrdenPendiente] = []

        if len(fechas) <= self.estrategia.minimo_barras:
            avisos.append(
                f"Historico corto: {len(fechas)} sesiones para una estrategia que "
                f"necesita {self.estrategia.minimo_barras}. Pide mas dias."
            )

        for fecha in fechas:
            precios_apertura: dict[str, float] = {}
            precios_cierre: dict[str, float] = {}
            barra_de: dict[str, Barra] = {}
            for simbolo, barras in datos.items():
                i = indices[simbolo].get(fecha)
                if i is None:
                    continue
                barra_de[simbolo] = barras[i]
                precios_apertura[simbolo] = barras[i].apertura
                precios_cierre[simbolo] = barras[i].cierre

            # 1) Ejecutar en la apertura las ordenes decididas ayer
            for orden in pendientes:
                barra = barra_de.get(orden.simbolo)
                if barra is None:
                    continue
                if orden.lado == "COMPRA":
                    self._abrir(cartera, gestor, broker, orden, barra,
                                datos[orden.simbolo], indices, precios_cierre)
                else:
                    self._cerrar(cartera, broker, orden.simbolo, barra.apertura,
                                 barra.fecha, orden.motivo)
            pendientes = []

            # 2) Stops y objetivos con el recorrido intradia de la barra
            for simbolo in list(cartera.posiciones):
                barra = barra_de.get(simbolo)
                if barra is None:
                    continue
                posicion = cartera.posiciones[simbolo]
                if not self.estrategia.gestionada:
                    continue
                hay_salida, precio, motivo = gestor.salida_forzosa(posicion, barra)
                if hay_salida:
                    self._cerrar(cartera, broker, simbolo, precio, barra.fecha, motivo)
                    continue
                historial = datos[simbolo][: indices[simbolo][fecha] + 1]
                gestor.actualizar_stop_dinamico(posicion, barra, historial)

            # 3) Senales con el cierre de hoy -> se ejecutan manana en la apertura
            for simbolo, barra in barra_de.items():
                historial = datos[simbolo][: indices[simbolo][fecha] + 1]
                en_posicion = simbolo in cartera.posiciones
                senal = self.estrategia.evaluar(historial, en_posicion)
                if senal.accion == "COMPRAR" and not en_posicion:
                    if not self.estrategia.gestionada or gestor.puede_abrir(len(cartera.posiciones)):
                        pendientes.append(
                            OrdenPendiente(simbolo, "COMPRA", senal.fuerza, senal.motivo))
                elif senal.accion == "VENDER" and en_posicion:
                    pendientes.append(
                        OrdenPendiente(simbolo, "VENTA", senal.fuerza, senal.motivo))

            valor = cartera.registrar(fecha, precios_cierre)
            if gestor.revisar_cortacircuitos(valor) and gestor.motivo_detencion \
                    and not any(a.startswith("Cortacircuitos") for a in avisos):
                avisos.append(
                    f"Cortacircuitos activado el {fecha}: {gestor.motivo_detencion}. "
                    "Mientras dura, no se abren posiciones nuevas."
                )

        # 4) Liquidar lo que quede abierto al ultimo cierre conocido
        ultima = fechas[-1] if fechas else ""
        for simbolo in list(cartera.posiciones):
            barras = datos[simbolo]
            i = indices[simbolo].get(ultima)
            barra = barras[i] if i is not None else barras[-1]
            self._cerrar(cartera, broker, simbolo, barra.cierre, barra.fecha, "cierre del periodo")
        if fechas:
            cartera.curva[-1] = (ultima, cartera.efectivo)

        final = cartera.curva[-1][1] if cartera.curva else self.capital
        metricas = calcular_metricas(cartera.curva, cartera.operaciones, self.capital)
        if metricas["operaciones"] == 0:
            avisos.append("La estrategia no genero ninguna operacion en este periodo.")
        elif metricas["costes"] > 0 and self.capital > 0 and \
                metricas["costes"] > self.capital * 0.1:
            avisos.append(
                f"Los costes ({metricas['costes']:.2f} EUR) superan el 10% del capital "
                f"inicial. Con cuentas pequenas hay que operar menos y con comisiones bajas."
            )
        return ResultadoBacktest(self.capital, final, cartera.curva, cartera.operaciones,
                                 metricas, avisos, cartera)

    # ------------------------------------------------------------------ ordenes
    def _abrir(self, cartera: Cartera, gestor: GestorRiesgo, broker: BrokerPapel,
               orden: OrdenPendiente, barra: Barra, barras: Sequence[Barra],
               indices: dict, precios_cierre: dict) -> None:
        if orden.simbolo in cartera.posiciones:
            return
        gestionada = self.estrategia.gestionada
        if gestionada and not gestor.puede_abrir(len(cartera.posiciones)):
            return
        historial = barras[: indices[orden.simbolo][barra.fecha] + 1]
        precio = barra.apertura
        capital_total = cartera.valor_total(precios_cierre)
        if gestionada:
            stop = gestor.calcular_stop(historial, precio)
            unidades = gestor.unidades(capital_total, cartera.efectivo, precio, stop,
                                       orden.fuerza)
        else:
            # referencia pasiva: invertir todo el efectivo, sin stops
            stop = None
            unidades = cartera.efectivo / precio
        unidades = unidades_asequibles(self.costes, cartera.efectivo, precio, unidades)
        minimo = (self.parametros_riesgo.importe_minimo if gestionada
                  else capital_total * 0.01)  # evita posiciones de calderilla
        if unidades <= 0 or unidades * precio < minimo:
            return
        ejecucion = broker.comprar(orden.simbolo, unidades, precio, barra.fecha)
        coste = -ejecucion.efectivo
        if coste > cartera.efectivo:  # sin efectivo suficiente tras costes
            broker.ejecuciones.pop()
            return
        cartera.efectivo -= coste
        cartera.posiciones[orden.simbolo] = Posicion(
            simbolo=orden.simbolo,
            unidades=unidades,
            precio_entrada=ejecucion.precio,
            fecha_entrada=barra.fecha,
            stop=stop,
            stop_inicial=stop,
            objetivo=gestor.calcular_objetivo(ejecucion.precio, stop) if stop else None,
            maximo_favorable=barra.maximo,
            comision_entrada=ejecucion.comision,
            capital_antes=capital_total,
        )

    def _cerrar(self, cartera: Cartera, broker: BrokerPapel, simbolo: str, precio: float,
                fecha: str, motivo: str) -> None:
        posicion = cartera.posiciones.pop(simbolo, None)
        if posicion is None:
            return
        ejecucion = broker.vender(simbolo, posicion.unidades, precio, fecha)
        cartera.efectivo += ejecucion.efectivo
        comision_entrada = posicion.comision_entrada
        capital_antes = posicion.capital_antes or cartera.efectivo
        cartera.operaciones.append(
            Operacion(
                simbolo=simbolo,
                fecha_entrada=posicion.fecha_entrada,
                fecha_salida=fecha,
                precio_entrada=posicion.precio_entrada,
                precio_salida=ejecucion.precio,
                unidades=posicion.unidades,
                comisiones=comision_entrada + ejecucion.comision,
                motivo_salida=motivo,
                capital_antes=capital_antes,
            )
        )
