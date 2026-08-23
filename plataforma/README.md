# Plataforma de inversión automática

Sistema completo de inversión algorítmica: descarga de datos de mercado, estrategias,
gestión de riesgo, bróker simulado, motor de *backtesting*, validación fuera de muestra,
simulación Monte Carlo, bot automático y panel web.

**Sin dependencias**: solo la biblioteca estándar de Python 3.10+. Nada que instalar.

---

## La pregunta de los 50 € → 100 €, respondida con honestidad

Esta plataforma nació de una petición concreta: *«que con 50 € sea capaz de duplicarlos»*.
La respuesta directa es que **ningún sistema, ni este ni ninguno, puede garantizar eso**.
Quien lo prometa está mintiendo o vendiendo algo. Lo que sí puede hacer un sistema serio
es decirte **qué probabilidad** tienes, y esta plataforma lo calcula (comando `montecarlo`).

Tres realidades que conviene tener delante antes de empezar:

**1. Duplicar es cuestión de tiempo compuesto, no de acertar una jugada.**

| Rentabilidad anual | Años en duplicar |
|---|---|
| 5 % | 14,2 |
| 8 % (media histórica de bolsa) | 9,0 |
| 10 % | 7,3 |
| 20 % (nivel de gestor excepcional) | 3,8 |
| 50 % | 1,7 |
| 100 % | 1,0 |

Warren Buffett ronda el 20 % anual sostenido y es el mejor de la historia. Un sistema que
promete duplicar en meses está prometiendo, implícitamente, batir a Buffett por goleada.

**2. Con 50 €, las comisiones son el enemigo principal.**

Ejecuta `python3 demo.py` y verás el efecto medido. Con una comisión de **1 € por orden**,
cada operación de ida y vuelta cuesta 2 €: un **4 % del capital** en costes antes de saber
si la idea era buena. Treinta operaciones y te has gastado el 100 % de la cuenta en peajes.
En la demostración, la misma estrategia termina en **53,93 €** sin comisiones y en
**33,80 €** con 1 € por orden. La estrategia no cambió; solo el bróker.

Con 50 €, la conclusión práctica es dura pero clara: **necesitas un bróker de fracciones sin
comisión fija, y operar poco.**

**3. La única forma de subir la probabilidad de duplicar rápido es subir también la de
arruinarte.** Están matemáticamente unidas. La simulación Monte Carlo de esta plataforma
muestra las dos cifras juntas, siempre, precisamente para que la decisión sea informada.

Resultado real de la demostración incluida (estrategia de cruce de medias, bróker del 0,05 %):

```
  25 operaciones -> P(duplicar)   0.0% | P(perder)  27.9% | mediana   52.37 EUR
 100 operaciones -> P(duplicar)   0.2% | P(perder)  10.4% | mediana   60.92 EUR
 400 operaciones -> P(duplicar)  69.9% | P(perder)   0.7% | mediana  111.37 EUR
```

Duplicar 50 € es perfectamente posible. Lo que no es posible es hacerlo rápido y sin riesgo.

---

## Instalación y primeros pasos

```bash
cd plataforma

python3 demo.py                      # recorrido completo sin conexión (datos simulados)
python3 -m unittest discover -s tests -t .    # 49 pruebas
python3 -m plataforma.cli --help
```

Panel web (se abre solo en el navegador, escucha únicamente en `127.0.0.1`):

```bash
python3 -m plataforma.cli web --puerto 8000
```

## Comandos

```bash
# Probar una estrategia sobre datos históricos reales
python3 -m plataforma.cli backtest -s SPY,QQQ -e cruce_medias -c 50 --operaciones

# Comparar todas las estrategias, incluida la referencia pasiva
python3 -m plataforma.cli comparar -s SPY,QQQ,AAPL -c 50

# ¿Qué probabilidad real hay de duplicar el capital?
python3 -m plataforma.cli montecarlo -s SPY -e momentum -c 50 --objetivo 2 --horizonte 200

# Buscar parámetros y validarlos en datos que la búsqueda no ha visto
python3 -m plataforma.cli optimizar -s SPY -e cruce_medias --metrica sharpe

# Bot automático en papel
python3 -m plataforma.cli bot reiniciar
python3 -m plataforma.cli bot ciclo
python3 -m plataforma.cli bot estado

# Guardar la configuración para no repetir opciones
python3 -m plataforma.cli config -s SPY,QQQ -e cruce_medias -c 50
```

Sin conexión a internet, añade `-p sintetico` a cualquier comando: la plataforma genera
series simuladas reproducibles y avisa por pantalla de que **no son datos reales**.

## Automatizar el bot

Un ciclo por sesión bursátil basta. Con `cron`, de lunes a viernes a las 22:10:

```cron
10 22 * * 1-5 cd /ruta/al/repo/plataforma && /usr/bin/python3 -m plataforma.cli bot ciclo >> bot.log 2>&1
```

El estado (efectivo, posiciones, operaciones y diario de decisiones) se guarda en
`estado_bot.json`, así que cada ejecución continúa donde lo dejó la anterior.

## Estrategias incluidas

| Nombre | Idea |
|---|---|
| `cruce_medias` | Seguimiento de tendencia: cruce de medias móviles con filtro de tendencia larga |
| `rsi_reversion` | Reversión a la media: compra sobreventa dentro de una tendencia alcista |
| `momentum` | Ruptura de máximos de N sesiones, salida por mínimos de M (estilo tortuga) |
| `tendencia_ema` | Cruce de EMAs con confirmación de impulso medida en ATR |
| `comprar_y_mantener` | **Referencia obligatoria.** Si una estrategia no bate a esto, no sirve |

La referencia pasiva aparece en todas las comparativas por diseño: es la vara de medir, y
en la mayoría de los periodos gana. Ese resultado incómodo es información valiosa.

## Gestión de riesgo

Con 50 €, el control de riesgo es lo único que separa «sigo en juego» de «me quedé a cero».
Todo es configurable en `config.json`:

| Parámetro | Por defecto | Qué hace |
|---|---|---|
| `riesgo_por_operacion` | 2 % | Pérdida máxima aceptada si salta el stop |
| `fraccion_maxima` | 50 % | Tope de capital en una sola posición |
| `multiplo_stop_atr` | 2,0 | Distancia del stop, medida en volatilidad real (ATR) |
| `multiplo_objetivo_r` | 3,0 | Objetivo de beneficio en múltiplos del riesgo |
| `stop_dinamico` / `dinamico_tras_r` | sí / 1,0 R | El stop sigue al precio, pero solo tras ganar 1R |
| `caida_maxima` / `sesiones_pausa` | 25 % / 20 | Cortacircuitos: deja de operar y espera |
| `posiciones_maximas` | 3 | Diversificación mínima sin dispersar una cuenta pequeña |
| `importe_minimo` | 10 € | Por debajo, las comisiones se comen la operación |

## Arquitectura

```
plataforma/
├── modelos.py       Barra, Señal, Posición, Operación, Cartera
├── datos.py         Yahoo · Stooq · CSV · sintético, con caché y respaldo automático
├── indicadores.py   SMA, EMA, RSI, ATR, Sharpe, Sortino, máxima caída, percentiles
├── estrategias.py   Estrategias + referencia pasiva
├── riesgo.py        Tamaño de posición, stops, cortacircuitos
├── broker.py        Costes reales, bróker de papel, hueco para bróker real
├── backtest.py      Motor sin sesgo de futuro + métricas
├── optimizador.py   Rejilla de parámetros con validación fuera de muestra
├── montecarlo.py    Probabilidad de duplicar y de arruinarse
├── bot.py           Bucle automático con estado persistente
├── api.py           Servidor HTTP y API JSON (solo stdlib)
├── cli.py           Interfaz de línea de comandos
└── web/             Panel: gráfico de capital, métricas, Monte Carlo, diario del bot
```

Decisiones de diseño que evitan resultados engañosos:

- Las señales se calculan con el cierre de la sesión `t` y **se ejecutan en la apertura de
  `t+1`**. El motor no puede mirar al futuro.
- Si en una misma sesión se tocan el stop y el objetivo, **se asume el stop** (el peor caso).
- Toda ejecución pasa por el bróker con **comisión y deslizamiento**.
- La optimización separa entrenamiento y validación, y **avisa explícitamente** cuando el
  resultado se degrada fuera de muestra.

## Operar con dinero real

La plataforma opera **siempre en papel**. `BrokerReal` (en `broker.py`) es un punto de
conexión deliberadamente sin implementar. Si algún día decides dar ese paso:

1. Opera en papel varios meses primero, con la estrategia y el capital que usarías de verdad.
2. Implementa `BrokerReal` con las credenciales de tu bróker, **fuera del repositorio**
   (variables de entorno, nunca en el código).
3. Empieza por el mínimo que puedas permitirte perder del todo.
4. La responsabilidad legal y económica es enteramente tuya.

## Aviso legal

Este software se distribuye con fines educativos. **No es asesoramiento financiero.**
Invertir en bolsa conlleva riesgo de pérdida, incluida la pérdida total del capital.
Los resultados pasados no garantizan resultados futuros. Ningún backtest, por bueno que
parezca, es una promesa sobre el futuro.
