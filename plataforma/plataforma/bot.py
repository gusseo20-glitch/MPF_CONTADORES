"""Bot de inversion automatica.

Ejecuta un ciclo de decision por sesion: descarga datos, revisa stops, pide
senal a la estrategia y manda las ordenes al broker. El estado (efectivo,
posiciones, operaciones y diario de decisiones) se guarda en un JSON, de modo
que se puede lanzar una vez al dia desde cron y continuar donde lo dejo.

Por defecto opera en PAPEL: no mueve dinero real en ninguna circunstancia.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .broker import SIN_COSTES, BrokerPapel, unidades_asequibles
from .config import Config
from .datos import ErrorDatos, crear_proveedor
from .estrategias import crear_estrategia
from .modelos import Cartera, Operacion, Posicion


class Bot:
    def __init__(self, config: Config | None = None, ruta_estado: str | None = None) -> None:
        self.config = config or Config()
        self.ruta_estado = ruta_estado or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), self.config.estado)
        self.proveedor = crear_proveedor(self.config.proveedor)
        self.estrategia = crear_estrategia(self.config.estrategia,
                                           **self.config.parametros_estrategia)
        self.broker = self._crear_broker()
        from .riesgo import GestorRiesgo  # import local: evita ciclo en herramientas
        self.gestor = GestorRiesgo(self.config.objeto_riesgo())
        self.cartera = Cartera(efectivo=self.config.capital)
        self.diario: list[dict] = []
        self.cargar_estado()

    def _crear_broker(self):
        """Elige el broker segun el modo configurado, con sus salvaguardas."""
        modo = self.config.modo
        if modo == "papel":
            return BrokerPapel(self.config.objeto_costes())
        if modo in ("alpaca_papel", "alpaca_real"):
            if modo == "alpaca_real" and os.environ.get("PLATAFORMA_DINERO_REAL") != "acepto":
                raise RuntimeError(
                    "modo alpaca_real: para operar con dinero real exporta "
                    "PLATAFORMA_DINERO_REAL=acepto — es tu confirmacion de que "
                    "asumes el riesgo de perdida, incluida la total"
                )
            from .alpaca import BrokerAlpaca, ClienteAlpaca
            return BrokerAlpaca(ClienteAlpaca(papel=(modo != "alpaca_real")))
        raise RuntimeError(f"modo desconocido: {modo} (papel | alpaca_papel | alpaca_real)")

    # ------------------------------------------------------------------ estado
    def cargar_estado(self) -> bool:
        if not os.path.exists(self.ruta_estado):
            return False
        try:
            with open(self.ruta_estado, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return False
        self.cartera.efectivo = float(datos.get("efectivo", self.config.capital))
        self.cartera.posiciones = {
            p["simbolo"]: Posicion(**p) for p in datos.get("posiciones", [])
        }
        self.cartera.operaciones = [Operacion(**o) for o in datos.get("operaciones", [])]
        self.cartera.curva = [tuple(c) for c in datos.get("curva", [])]
        self.diario = datos.get("diario", [])
        self.gestor.pico_capital = float(datos.get("pico_capital", 0.0))
        self.gestor.detenido = bool(datos.get("detenido", False))
        self.gestor.motivo_detencion = datos.get("motivo_detencion", "")
        return True

    def guardar_estado(self) -> str:
        datos = {
            "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "modo": self.config.modo,
            "estrategia": self.config.estrategia,
            "capital_inicial": self.config.capital,
            "efectivo": round(self.cartera.efectivo, 6),
            "posiciones": [
                {k: v for k, v in p.__dict__.items()} for p in self.cartera.posiciones.values()
            ],
            "operaciones": [o.__dict__ for o in self.cartera.operaciones],
            "curva": [list(c) for c in self.cartera.curva],
            "diario": self.diario[-500:],
            "pico_capital": self.gestor.pico_capital,
            "detenido": self.gestor.detenido,
            "motivo_detencion": self.gestor.motivo_detencion,
        }
        with open(self.ruta_estado, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, indent=2, ensure_ascii=False)
        return self.ruta_estado

    def reiniciar(self) -> None:
        self.cartera = Cartera(efectivo=self.config.capital)
        self.diario = []
        self.gestor.pico_capital = 0.0
        self.gestor.detenido = False
        self.gestor.motivo_detencion = ""
        self.guardar_estado()

    # ------------------------------------------------------------------- ciclo
    def _anotar(self, tipo: str, simbolo: str, mensaje: str, **extra) -> dict:
        entrada = {
            "momento": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tipo": tipo,
            "simbolo": simbolo,
            "mensaje": mensaje,
        }
        entrada.update(extra)
        self.diario.append(entrada)
        return entrada

    def ejecutar_ciclo(self) -> dict:
        """Un ciclo completo de decision sobre todos los simbolos configurados."""
        acciones: list[dict] = []
        precios: dict[str, float] = {}
        historicos: dict[str, list] = {}

        for simbolo in self.config.simbolos:
            try:
                barras = self.proveedor.historico(simbolo, self.config.dias)
            except ErrorDatos as exc:
                acciones.append(self._anotar("error", simbolo, f"sin datos: {exc}"))
                continue
            if not barras:
                continue
            historicos[simbolo] = barras
            precios[simbolo] = barras[-1].cierre

        # 1) stops y objetivos sobre la ultima barra conocida
        for simbolo in list(self.cartera.posiciones):
            barras = historicos.get(simbolo)
            if not barras:
                continue
            posicion = self.cartera.posiciones[simbolo]
            hay_salida, precio, motivo = self.gestor.salida_forzosa(posicion, barras[-1])
            if hay_salida:
                acciones.append(self._vender(simbolo, precio, barras[-1].fecha, motivo))
            else:
                self.gestor.actualizar_stop_dinamico(posicion, barras[-1], barras)

        # 2) senales
        for simbolo, barras in historicos.items():
            en_posicion = simbolo in self.cartera.posiciones
            senal = self.estrategia.evaluar(barras, en_posicion)
            if senal.accion == "MANTENER":
                continue
            if senal.accion == "COMPRAR" and not en_posicion:
                if not self.gestor.puede_abrir(len(self.cartera.posiciones)):
                    acciones.append(self._anotar(
                        "bloqueada", simbolo,
                        "senal de compra bloqueada por gestion de riesgo: " +
                        (self.gestor.motivo_detencion or "limite de posiciones abiertas")))
                    continue
                acciones.append(self._comprar(simbolo, barras, senal, precios))
            elif senal.accion == "VENDER" and en_posicion:
                acciones.append(self._vender(simbolo, barras[-1].cierre, barras[-1].fecha,
                                             senal.motivo))

        valor = self.cartera.valor_total(precios)
        fecha = max((b[-1].fecha for b in historicos.values()), default="")
        if fecha:
            if self.cartera.curva and self.cartera.curva[-1][0] == fecha:
                self.cartera.curva[-1] = (fecha, valor)
            else:
                self.cartera.curva.append((fecha, valor))
        if self.gestor.revisar_cortacircuitos(valor) and self.gestor.motivo_detencion:
            acciones.append(self._anotar("cortacircuitos", "",
                                         self.gestor.motivo_detencion))
        if not acciones:
            acciones.append(self._anotar("sin_cambios", "", "ninguna senal: no se opera hoy"))

        self.guardar_estado()
        return {
            "fecha": fecha,
            "valor_cartera": round(valor, 2),
            "efectivo": round(self.cartera.efectivo, 2),
            "capital_inicial": self.config.capital,
            "rendimiento": round(valor / self.config.capital - 1, 6) if self.config.capital else 0,
            "posiciones": len(self.cartera.posiciones),
            "detenido": self.gestor.detenido,
            "acciones": acciones,
            "avisos": getattr(self.proveedor, "avisos", [])[-3:],
        }

    # ----------------------------------------------------------------- ordenes
    def _comprar(self, simbolo, barras, senal, precios) -> dict:
        precio = barras[-1].cierre
        stop = self.gestor.calcular_stop(barras, precio)
        capital_total = self.cartera.valor_total(precios)
        unidades = self.gestor.unidades(capital_total, self.cartera.efectivo, precio, stop,
                                        senal.fuerza)
        costes = getattr(self.broker, "costes", SIN_COSTES)
        unidades = unidades_asequibles(costes, self.cartera.efectivo, precio, unidades)
        if unidades <= 0 or unidades * precio < self.gestor.p.importe_minimo:
            return self._anotar(
                "descartada", simbolo,
                f"senal de compra descartada: el tamano de posicion no llega al minimo "
                f"de {self.gestor.p.importe_minimo:.2f} EUR")
        ejecucion = self.broker.comprar(simbolo, unidades, precio, barras[-1].fecha)
        coste = -ejecucion.efectivo
        if coste > self.cartera.efectivo and not self.broker.irreversible:
            self.broker.ejecuciones.pop()
            return self._anotar("descartada", simbolo, "efectivo insuficiente tras comisiones")
        self.cartera.efectivo -= coste
        self.cartera.posiciones[simbolo] = Posicion(
            simbolo=simbolo, unidades=ejecucion.unidades, precio_entrada=ejecucion.precio,
            fecha_entrada=barras[-1].fecha, stop=stop, stop_inicial=stop,
            objetivo=self.gestor.calcular_objetivo(ejecucion.precio, stop),
            maximo_favorable=barras[-1].maximo, comision_entrada=ejecucion.comision,
            capital_antes=capital_total)
        return self._anotar("compra", simbolo, senal.motivo,
                            unidades=round(unidades, 6), precio=round(ejecucion.precio, 4),
                            importe=round(ejecucion.importe, 2), stop=round(stop, 4))

    def _vender(self, simbolo, precio, fecha, motivo) -> dict:
        posicion = self.cartera.posiciones.pop(simbolo, None)
        if posicion is None:
            return self._anotar("error", simbolo, "venta sin posicion abierta")
        ejecucion = self.broker.vender(simbolo, posicion.unidades, precio, fecha)
        self.cartera.efectivo += ejecucion.efectivo
        operacion = Operacion(
            simbolo=simbolo, fecha_entrada=posicion.fecha_entrada, fecha_salida=fecha,
            precio_entrada=posicion.precio_entrada, precio_salida=ejecucion.precio,
            unidades=posicion.unidades,
            comisiones=posicion.comision_entrada + ejecucion.comision,
            motivo_salida=motivo, capital_antes=posicion.capital_antes or self.cartera.efectivo)
        self.cartera.operaciones.append(operacion)
        return self._anotar("venta", simbolo, motivo, unidades=round(posicion.unidades, 6),
                            precio=round(ejecucion.precio, 4),
                            beneficio=round(operacion.beneficio, 2))

    # ------------------------------------------------------------ sincronizar
    def sincronizar(self) -> dict:
        """Trae del broker (Alpaca) el efectivo y las posiciones reales.

        Cuadra la cartera local con la del broker: es lo que arregla cualquier
        deriva (ordenes en cola que se ejecutaron mas tarde, redondeos...).
        """
        cliente = getattr(self.broker, "cliente", None)
        if cliente is None:
            raise RuntimeError(
                "sincronizar solo tiene sentido con un broker Alpaca "
                "(modo alpaca_papel o alpaca_real)"
            )
        cuenta = cliente.cuenta()
        remotas = cliente.posiciones()
        self.cartera.efectivo = float(cuenta.get("cash", 0.0))
        nuevas: dict[str, Posicion] = {}
        for remota in remotas:
            simbolo = remota["symbol"]
            unidades = float(remota["qty"])
            entrada = float(remota["avg_entry_price"])
            previa = self.cartera.posiciones.get(simbolo)
            stop = previa.stop if previa else None
            if stop is None:
                try:
                    barras = self.proveedor.historico(simbolo, 60)
                    stop = self.gestor.calcular_stop(barras, entrada)
                except ErrorDatos:
                    stop = entrada * 0.92
            nuevas[simbolo] = Posicion(
                simbolo=simbolo, unidades=unidades, precio_entrada=entrada,
                fecha_entrada=(previa.fecha_entrada if previa
                               else datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                stop=stop,
                stop_inicial=(previa.stop_inicial if previa else stop),
                objetivo=(previa.objetivo if previa
                          else self.gestor.calcular_objetivo(entrada, stop)),
                maximo_favorable=(previa.maximo_favorable if previa else entrada),
                comision_entrada=(previa.comision_entrada if previa else 0.0),
                capital_antes=(previa.capital_antes if previa
                               else float(cuenta.get("equity", 0.0) or 0.0)),
            )
        self.cartera.posiciones = nuevas
        self._anotar("sincronizacion", "",
                     f"{len(nuevas)} posiciones y {self.cartera.efectivo:.2f} de "
                     "efectivo traidos del broker")
        self.guardar_estado()
        return {
            "modo": self.config.modo,
            "efectivo": round(self.cartera.efectivo, 2),
            "posiciones": [
                {"simbolo": q.simbolo, "unidades": q.unidades,
                 "precio_entrada": q.precio_entrada,
                 "stop": round(q.stop, 4) if q.stop else None}
                for q in nuevas.values()
            ],
        }

    # ---------------------------------------------------------------- consulta
    def estado(self) -> dict:
        precios: dict[str, float] = {}
        for simbolo in self.cartera.posiciones:
            try:
                precios[simbolo] = self.proveedor.ultimo_precio(simbolo)
            except ErrorDatos:
                precios[simbolo] = self.cartera.posiciones[simbolo].precio_entrada
        valor = self.cartera.valor_total(precios)
        return {
            "modo": self.config.modo,
            "estrategia": self.config.estrategia,
            "simbolos": self.config.simbolos,
            "capital_inicial": self.config.capital,
            "valor_cartera": round(valor, 2),
            "rendimiento": round(valor / self.config.capital - 1, 6) if self.config.capital else 0,
            "detenido": self.gestor.detenido,
            "motivo_detencion": self.gestor.motivo_detencion,
            "cartera": self.cartera.a_dict(precios),
            "curva": [list(c) for c in self.cartera.curva],
            "diario": self.diario[-50:][::-1],
        }
