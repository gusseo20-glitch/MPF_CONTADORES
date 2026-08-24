"""Interfaz de linea de comandos de la plataforma.

    python -m plataforma.cli --ayuda
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, montecarlo
from .backtest import MotorBacktest
from .bot import Bot
from .broker import Costes
from .config import Config, RUTA_POR_DEFECTO
from .datos import ErrorDatos, crear_proveedor
from .estrategias import ESTRATEGIAS, crear_estrategia
from .optimizador import optimizar
from .riesgo import ParametrosRiesgo

AVISO = """
=============================================================================
 AVISO: invertir en bolsa puede hacerte perder dinero, incluido todo el
 capital. Esta plataforma opera POR DEFECTO EN PAPEL (dinero simulado).
 Ningun sistema puede garantizar que 50 EUR se conviertan en 100.
 Esto no es asesoramiento financiero.
=============================================================================
"""


def _config_desde_args(args) -> Config:
    config = Config.cargar(getattr(args, "config", RUTA_POR_DEFECTO))
    if getattr(args, "capital", None) is not None:
        config.capital = args.capital
    if getattr(args, "simbolos", None):
        config.simbolos = [s.strip().upper() for s in args.simbolos.split(",") if s.strip()]
    if getattr(args, "estrategia", None):
        config.estrategia = args.estrategia
    if getattr(args, "proveedor", None):
        config.proveedor = args.proveedor
    if getattr(args, "dias", None):
        config.dias = args.dias
    if getattr(args, "comision", None) is not None:
        config.costes["comision_fija"] = args.comision
    if getattr(args, "riesgo", None) is not None:
        config.riesgo["riesgo_por_operacion"] = args.riesgo
    if getattr(args, "modo", None):
        config.modo = args.modo
    return config


def _descargar(config: Config, verboso: bool = True) -> dict:
    proveedor = crear_proveedor(config.proveedor)
    datos = {}
    for simbolo in config.simbolos:
        try:
            barras = proveedor.historico(simbolo, config.dias)
            datos[simbolo] = barras
            if verboso:
                print(f"  {simbolo:8s} {len(barras):5d} sesiones "
                      f"({barras[0].fecha} -> {barras[-1].fecha})")
        except ErrorDatos as exc:
            print(f"  {simbolo:8s} ERROR: {exc}", file=sys.stderr)
    for aviso in getattr(proveedor, "avisos", [])[-1:]:
        if "SIMULADA" in aviso:
            print(f"\n  !! {aviso}\n")
    if not datos:
        raise SystemExit("No se pudo descargar ningun dato. Revisa simbolos y conexion.")
    return datos


# ------------------------------------------------------------------- comandos
def cmd_backtest(args) -> int:
    config = _config_desde_args(args)
    print(AVISO)
    print(f"Backtest: {config.estrategia} sobre {', '.join(config.simbolos)} "
          f"con {config.capital:.2f} EUR\n")
    datos = _descargar(config)
    estrategia = crear_estrategia(config.estrategia, **config.parametros_estrategia)
    resultado = MotorBacktest(estrategia, config.capital, config.objeto_costes(),
                              config.objeto_riesgo()).ejecutar(datos)
    print("\n" + resultado.resumen())
    for aviso in resultado.avisos:
        print(f"\n  !! {aviso}")

    referencia = MotorBacktest(crear_estrategia("comprar_y_mantener"), config.capital,
                               config.objeto_costes(), config.objeto_riesgo()).ejecutar(datos)
    print(f"\nReferencia comprar y mantener: {referencia.capital_final:,.2f} EUR "
          f"({referencia.metricas['rendimiento_total']:+.2%})")
    if resultado.capital_final <= referencia.capital_final:
        print("  -> La estrategia automatica NO bate a no hacer nada en este periodo.")

    if args.operaciones:
        print("\nOperaciones:")
        for o in resultado.operaciones:
            print(f"  {o.fecha_entrada} -> {o.fecha_salida} {o.simbolo:6s} "
                  f"{o.precio_entrada:9.2f} -> {o.precio_salida:9.2f} "
                  f"{o.beneficio:+8.2f} EUR  ({o.motivo_salida})")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(resultado.a_dict(), fh, indent=2, ensure_ascii=False)
        print(f"\nResultado guardado en {args.json}")
    return 0


def cmd_comparar(args) -> int:
    config = _config_desde_args(args)
    print(AVISO)
    datos = _descargar(config)
    print(f"\n{'Estrategia':22s} {'Final':>10s} {'Rend.':>9s} {'Sharpe':>7s} "
          f"{'Caida':>8s} {'Ops':>5s} {'Costes':>8s}")
    print("-" * 74)
    filas = []
    for nombre in ESTRATEGIAS:
        resultado = MotorBacktest(crear_estrategia(nombre), config.capital,
                                  config.objeto_costes(), config.objeto_riesgo()).ejecutar(datos)
        m = resultado.metricas
        filas.append((nombre, resultado.capital_final, m))
        print(f"{nombre:22s} {resultado.capital_final:10.2f} "
              f"{m['rendimiento_total']:+8.2%} {m['sharpe']:7.2f} "
              f"{-m['maxima_caida']:8.2%} {m['operaciones']:5d} {m['costes']:8.2f}")
    mejor = max(filas, key=lambda f: f[1])
    print(f"\nMejor en este periodo: {mejor[0]} ({mejor[1]:.2f} EUR).")
    print("Que haya sido la mejor en el pasado no la convierte en la mejor manana.")
    return 0


def cmd_optimizar(args) -> int:
    config = _config_desde_args(args)
    print(AVISO)
    datos = _descargar(config)
    print(f"\nOptimizando '{config.estrategia}' con validacion fuera de muestra...\n")
    combinaciones, diagnostico = optimizar(
        config.estrategia, datos, config.capital, config.objeto_costes(),
        config.objeto_riesgo(), metrica=args.metrica,
        fraccion_entrenamiento=args.entrenamiento)
    if not combinaciones:
        print(diagnostico)
        return 1
    print(f"{'Parametros':52s} {'dentro':>8s} {'fuera':>8s} {'Final':>9s}")
    print("-" * 82)
    for c in combinaciones[:args.top]:
        print(f"{json.dumps(c.parametros, ensure_ascii=False):52s} "
              f"{c.metrica_dentro:8.2f} {c.metrica_fuera:8.2f} {c.capital_final_fuera:9.2f}")
    print("\n" + diagnostico)
    return 0


def cmd_montecarlo(args) -> int:
    config = _config_desde_args(args)
    print(AVISO)
    datos = _descargar(config)
    resultado = MotorBacktest(crear_estrategia(config.estrategia, **config.parametros_estrategia),
                              config.capital, config.objeto_costes(),
                              config.objeto_riesgo()).ejecutar(datos)
    print("\n" + resultado.resumen())
    try:
        if args.metodo == "diario":
            mc = montecarlo.desde_curva(resultado.curva, config.capital,
                                        horizonte=args.horizonte,
                                        simulaciones=args.simulaciones, objetivo=args.objetivo)
        else:
            mc = montecarlo.desde_operaciones(resultado.operaciones, config.capital,
                                              horizonte=args.horizonte,
                                              simulaciones=args.simulaciones,
                                              objetivo=args.objetivo)
    except ValueError as exc:
        print(f"\nNo se puede simular: {exc}")
        return 1
    print("\n" + "=" * 70)
    print(mc.resumen())
    print("=" * 70)
    if mc.prob_objetivo < 0.10:
        print("\nLectura: con esta estrategia y este horizonte, duplicar el capital es\n"
              "muy improbable. Alargar el plazo o asumir mas riesgo sube esa\n"
              "probabilidad, pero sube tambien la de perderlo todo.")
    return 0


def cmd_bot(args) -> int:
    config = _config_desde_args(args)
    try:
        bot = Bot(config)
    except RuntimeError as exc:
        print(f"No se pudo arrancar el bot: {exc}", file=sys.stderr)
        return 1
    if config.modo == "alpaca_real":
        print("!! MODO DINERO REAL: las ordenes de este ciclo se envian al mercado.")
    if args.accion == "reiniciar":
        bot.reiniciar()
        print(f"Estado reiniciado con {config.capital:.2f} EUR en {bot.ruta_estado}")
        return 0
    if args.accion == "estado":
        print(json.dumps(bot.estado(), indent=2, ensure_ascii=False))
        return 0
    if args.accion == "sincronizar":
        try:
            print(json.dumps(bot.sincronizar(), indent=2, ensure_ascii=False))
        except RuntimeError as exc:
            print(f"No se pudo sincronizar: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        resultado = bot.ejecutar_ciclo()
    except RuntimeError as exc:
        print(f"El ciclo fallo: {exc}", file=sys.stderr)
        return 1
    print(f"[{resultado['fecha']}] cartera {resultado['valor_cartera']:.2f} EUR "
          f"({resultado['rendimiento']:+.2%}) | efectivo {resultado['efectivo']:.2f} | "
          f"{resultado['posiciones']} posiciones")
    for accion in resultado["acciones"]:
        simbolo = f"[{accion['simbolo']}] " if accion["simbolo"] else ""
        print(f"  {accion['tipo']:14s} {simbolo}{accion['mensaje']}")
    if resultado["detenido"]:
        print("  !! operativa detenida por el cortacircuitos de riesgo")
    return 0


def cmd_cuenta(args) -> int:
    config = _config_desde_args(args)
    from .alpaca import ClienteAlpaca, ErrorAlpaca
    papel = config.modo != "alpaca_real"
    try:
        cliente = ClienteAlpaca(papel=papel)
        cuenta = cliente.cuenta()
        reloj = cliente.reloj()
        posiciones = cliente.posiciones()
    except (ErrorAlpaca, RuntimeError) as exc:
        print(f"No se pudo consultar Alpaca: {exc}", file=sys.stderr)
        return 1
    entorno = "PAPER (practica)" if papel else "DINERO REAL"
    print(f"Cuenta Alpaca [{entorno}]")
    print(f"  estado    : {cuenta.get('status')}")
    print(f"  efectivo  : {float(cuenta.get('cash', 0)):,.2f} USD")
    print(f"  cartera   : {float(cuenta.get('equity', 0)):,.2f} USD")
    print(f"  mercado   : {'ABIERTO' if reloj.get('is_open') else 'cerrado'} "
          f"(proxima apertura {reloj.get('next_open', '?')})")
    if posiciones:
        print("  posiciones:")
        for p in posiciones:
            print(f"    {p['symbol']:6s} {float(p['qty']):>10.4f} unid. "
                  f"entrada {float(p['avg_entry_price']):>9.2f} "
                  f"actual {float(p.get('current_price', 0) or 0):>9.2f} "
                  f"P/L {float(p.get('unrealized_pl', 0) or 0):>+8.2f} USD")
    else:
        print("  posiciones: ninguna")
    return 0


def cmd_web(args) -> int:
    from .api import servir
    config = _config_desde_args(args)
    servir(config, args.puerto, args.host)
    return 0


def cmd_config(args) -> int:
    config = _config_desde_args(args)
    ruta = config.guardar(args.config)
    print(f"Configuracion guardada en {ruta}:\n")
    print(json.dumps(config.a_dict(), indent=2, ensure_ascii=False))
    return 0


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plataforma",
        description="Plataforma de inversion automatica (modo papel por defecto).",
        epilog="Ejemplo: python -m plataforma.cli backtest -s SPY,QQQ -e cruce_medias")
    p.add_argument("--version", action="version", version=f"plataforma {__version__}")
    sub = p.add_subparsers(dest="comando", required=True)

    def comunes(sp):
        sp.add_argument("-s", "--simbolos", help="lista separada por comas (SPY,QQQ,AAPL)")
        sp.add_argument("-e", "--estrategia", choices=sorted(ESTRATEGIAS))
        sp.add_argument("-c", "--capital", type=float, help="capital inicial en EUR")
        sp.add_argument("-d", "--dias", type=int, help="sesiones de historico")
        sp.add_argument("-p", "--proveedor",
                        choices=["auto", "yahoo", "stooq", "csv", "sintetico"])
        sp.add_argument("--comision", type=float, help="comision fija por orden en EUR")
        sp.add_argument("--riesgo", type=float,
                        help="fraccion del capital arriesgada por operacion (0.02 = 2%%)")
        sp.add_argument("--modo", choices=["papel", "alpaca_papel", "alpaca_real"],
                        help="papel local, paper de Alpaca o dinero real")
        sp.add_argument("--config", default=RUTA_POR_DEFECTO)
        return sp

    b = comunes(sub.add_parser("backtest", help="prueba una estrategia sobre el historico"))
    b.add_argument("--operaciones", action="store_true", help="listar todas las operaciones")
    b.add_argument("--json", help="guardar el resultado en un fichero JSON")
    b.set_defaults(func=cmd_backtest)

    c = comunes(sub.add_parser("comparar", help="compara todas las estrategias"))
    c.set_defaults(func=cmd_comparar)

    o = comunes(sub.add_parser("optimizar", help="busca parametros con validacion"))
    o.add_argument("--metrica", default="sharpe", choices=["sharpe", "rendimiento", "calmar"])
    o.add_argument("--entrenamiento", type=float, default=0.7,
                   help="fraccion del historico usada para buscar (resto para validar)")
    o.add_argument("--top", type=int, default=10)
    o.set_defaults(func=cmd_optimizar)

    m = comunes(sub.add_parser("montecarlo",
                               help="probabilidad real de duplicar el capital"))
    m.add_argument("--objetivo", type=float, default=2.0, help="multiplicador buscado")
    m.add_argument("--horizonte", type=int, default=100,
                   help="operaciones (o sesiones) simuladas por camino")
    m.add_argument("--simulaciones", type=int, default=10_000)
    m.add_argument("--metodo", default="operaciones", choices=["operaciones", "diario"])
    m.set_defaults(func=cmd_montecarlo)

    t = comunes(sub.add_parser("bot", help="ejecuta el bot automatico en papel"))
    t.add_argument("accion", choices=["ciclo", "estado", "reiniciar", "sincronizar"],
                   nargs="?", default="ciclo")
    t.set_defaults(func=cmd_bot)

    q = comunes(sub.add_parser("cuenta", help="cuenta y posiciones en Alpaca"))
    q.set_defaults(func=cmd_cuenta)

    w = comunes(sub.add_parser("web", help="panel web en el navegador"))
    w.add_argument("--puerto", type=int, default=8000)
    w.add_argument("--host", default="127.0.0.1")
    w.set_defaults(func=cmd_web)

    g = comunes(sub.add_parser("config", help="crea o actualiza config.json"))
    g.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
