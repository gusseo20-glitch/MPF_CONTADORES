"""Estrategias de inversion.

Una estrategia recibe el historial de barras (solo hasta la barra actual, sin
mirar al futuro) y devuelve una `Senal`. El motor de backtest y el bot en vivo
usan exactamente el mismo codigo, de modo que lo que pruebas es lo que operas.
"""

from __future__ import annotations

from typing import Sequence

from .indicadores import atr, cierres, ema, rsi, sma, serie_sma
from .modelos import Barra, Senal, MANTENER


class Estrategia:
    """Interfaz comun de todas las estrategias."""

    nombre = "base"
    descripcion = ""
    #: barras minimas necesarias antes de emitir la primera senal
    minimo_barras = 2
    #: si es False, la estrategia se ejecuta sin stops ni limites de riesgo
    #: (solo tiene sentido para la referencia pasiva de comparacion)
    gestionada = True

    def __init__(self, **parametros) -> None:
        self.parametros = parametros

    def evaluar(self, historial: Sequence[Barra], en_posicion: bool) -> Senal:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - utilidad de depuracion
        return f"{self.__class__.__name__}({self.parametros})"


class CruceMedias(Estrategia):
    """Cruce de medias moviles: tendencia seguida, la mas clasica.

    Compra cuando la media rapida cruza por encima de la lenta y el precio esta
    por encima de la media larga (filtro de tendencia); vende en el cruce
    contrario.
    """

    nombre = "cruce_medias"
    descripcion = "Cruce de medias moviles con filtro de tendencia"

    def __init__(self, rapida: int = 20, lenta: int = 50, filtro: int = 200) -> None:
        super().__init__(rapida=rapida, lenta=lenta, filtro=filtro)
        self.rapida = rapida
        self.lenta = lenta
        self.filtro = filtro
        self.minimo_barras = max(lenta, filtro) + 2

    def evaluar(self, historial: Sequence[Barra], en_posicion: bool) -> Senal:
        precios = cierres(historial)
        if len(precios) < self.minimo_barras:
            return MANTENER
        rapida_hoy = sma(precios, self.rapida)
        lenta_hoy = sma(precios, self.lenta)
        rapida_ayer = sma(precios[:-1], self.rapida)
        lenta_ayer = sma(precios[:-1], self.lenta)
        if None in (rapida_hoy, lenta_hoy, rapida_ayer, lenta_ayer):
            return MANTENER
        tendencia = sma(precios, self.filtro) if self.filtro else 0.0
        cruce_alcista = rapida_ayer <= lenta_ayer and rapida_hoy > lenta_hoy
        cruce_bajista = rapida_ayer >= lenta_ayer and rapida_hoy < lenta_hoy

        if not en_posicion and cruce_alcista and (not tendencia or precios[-1] > tendencia):
            distancia = (rapida_hoy - lenta_hoy) / lenta_hoy if lenta_hoy else 0.0
            return Senal("COMPRAR", min(1.0, 0.5 + abs(distancia) * 20),
                         f"cruce alcista {self.rapida}/{self.lenta}")
        if en_posicion and cruce_bajista:
            return Senal("VENDER", 1.0, f"cruce bajista {self.rapida}/{self.lenta}")
        return MANTENER


class RSIReversion(Estrategia):
    """Reversion a la media: compra sobreventa dentro de tendencia alcista."""

    nombre = "rsi_reversion"
    descripcion = "Compra en sobreventa (RSI) con filtro de tendencia alcista"

    def __init__(self, periodo: int = 14, compra: float = 35.0, venta: float = 60.0,
                 filtro: int = 200) -> None:
        super().__init__(periodo=periodo, compra=compra, venta=venta, filtro=filtro)
        self.periodo = periodo
        self.compra = compra
        self.venta = venta
        self.filtro = filtro
        self.minimo_barras = max(periodo * 3, filtro) + 2

    def evaluar(self, historial: Sequence[Barra], en_posicion: bool) -> Senal:
        precios = cierres(historial)
        if len(precios) < self.minimo_barras:
            return MANTENER
        valor = rsi(precios, self.periodo)
        if valor is None:
            return MANTENER
        tendencia = sma(precios, self.filtro) if self.filtro else 0.0
        if not en_posicion and valor <= self.compra and (not tendencia or precios[-1] > tendencia):
            fuerza = min(1.0, (self.compra - valor) / max(self.compra, 1.0) + 0.5)
            return Senal("COMPRAR", fuerza, f"RSI {valor:.1f} en sobreventa")
        if en_posicion and valor >= self.venta:
            return Senal("VENDER", 1.0, f"RSI {valor:.1f} recuperado")
        return MANTENER


class MomentumRuptura(Estrategia):
    """Ruptura de maximos de N sesiones (momentum tipo tortuga)."""

    nombre = "momentum"
    descripcion = "Ruptura de maximos de N sesiones, salida por minimos de M"

    def __init__(self, entrada: int = 55, salida: int = 20, filtro: int = 100) -> None:
        super().__init__(entrada=entrada, salida=salida, filtro=filtro)
        self.entrada = entrada
        self.salida = salida
        self.filtro = filtro
        self.minimo_barras = max(entrada, salida, filtro) + 2

    def evaluar(self, historial: Sequence[Barra], en_posicion: bool) -> Senal:
        if len(historial) < self.minimo_barras:
            return MANTENER
        precios = cierres(historial)
        actual = historial[-1].cierre
        previas = historial[:-1]
        maximo_n = max(b.maximo for b in previas[-self.entrada:])
        minimo_m = min(b.minimo for b in previas[-self.salida:])
        tendencia = sma(precios, self.filtro) if self.filtro else 0.0
        if not en_posicion and actual > maximo_n and (not tendencia or actual > tendencia):
            return Senal("COMPRAR", 0.8, f"ruptura de maximos de {self.entrada} sesiones")
        if en_posicion and actual < minimo_m:
            return Senal("VENDER", 1.0, f"perdida de minimos de {self.salida} sesiones")
        return MANTENER


class TendenciaEMA(Estrategia):
    """Seguimiento de tendencia con EMA y confirmacion de volatilidad (ATR)."""

    nombre = "tendencia_ema"
    descripcion = "EMA rapida sobre lenta con confirmacion por ATR"

    def __init__(self, rapida: int = 12, lenta: int = 26, periodo_atr: int = 14,
                 umbral_atr: float = 0.2) -> None:
        super().__init__(rapida=rapida, lenta=lenta, periodo_atr=periodo_atr,
                         umbral_atr=umbral_atr)
        self.rapida = rapida
        self.lenta = lenta
        self.periodo_atr = periodo_atr
        self.umbral_atr = umbral_atr
        self.minimo_barras = lenta + periodo_atr + 2

    def evaluar(self, historial: Sequence[Barra], en_posicion: bool) -> Senal:
        precios = cierres(historial)
        if len(precios) < self.minimo_barras:
            return MANTENER
        rapida = ema(precios, self.rapida)
        lenta = ema(precios, self.lenta)
        rapida_ayer = ema(precios[:-1], self.rapida)
        lenta_ayer = ema(precios[:-1], self.lenta)
        rango = atr(historial, self.periodo_atr)
        if None in (rapida, lenta, rapida_ayer, lenta_ayer, rango) or rango == 0:
            return MANTENER
        # La separacion se mide entre el precio y la EMA lenta: en el propio
        # cruce las dos medias coinciden, asi que compararlas entre si filtraria
        # practicamente todas las entradas.
        separacion = (precios[-1] - lenta) / rango
        if not en_posicion and rapida_ayer <= lenta_ayer and rapida > lenta \
                and separacion >= self.umbral_atr:
            return Senal("COMPRAR", min(1.0, separacion), "EMA cruza al alza con impulso")
        if en_posicion and rapida < lenta:
            return Senal("VENDER", 1.0, "EMA cruza a la baja")
        return MANTENER


class CompraYMantiene(Estrategia):
    """Referencia obligatoria: comprar el primer dia y no tocar nada.

    Cualquier estrategia automatica que no bata a esto (despues de costes) no
    merece la pena. Se incluye para que la comparacion sea siempre visible.
    """

    nombre = "comprar_y_mantener"
    descripcion = "Referencia pasiva: comprar y no vender nunca"
    minimo_barras = 1
    gestionada = False

    def evaluar(self, historial: Sequence[Barra], en_posicion: bool) -> Senal:
        if not en_posicion:
            return Senal("COMPRAR", 1.0, "compra inicial")
        return MANTENER


ESTRATEGIAS: dict[str, type[Estrategia]] = {
    CruceMedias.nombre: CruceMedias,
    RSIReversion.nombre: RSIReversion,
    MomentumRuptura.nombre: MomentumRuptura,
    TendenciaEMA.nombre: TendenciaEMA,
    CompraYMantiene.nombre: CompraYMantiene,
}


def crear_estrategia(nombre: str, **parametros) -> Estrategia:
    if nombre not in ESTRATEGIAS:
        disponibles = ", ".join(sorted(ESTRATEGIAS))
        raise ValueError(f"estrategia desconocida '{nombre}'. Disponibles: {disponibles}")
    return ESTRATEGIAS[nombre](**parametros)
