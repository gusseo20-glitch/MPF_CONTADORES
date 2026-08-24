'use strict';

const $ = (id) => document.getElementById(id);
const eur = (v) => `${Number(v).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const pct = (v) => `${(Number(v) * 100).toFixed(2).replace('.', ',')} %`;
const signo = (v) => (v >= 0 ? 'positivo' : 'negativo');

function parametros() {
  return {
    capital: parseFloat($('capital').value) || 50,
    simbolos: $('simbolos').value,
    estrategia: $('estrategia').value,
    dias: parseInt($('dias').value, 10) || 750,
    comision: parseFloat($('comision').value) || 0,
    riesgo: parseFloat($('riesgo').value),
    proveedor: $('proveedor').value,
  };
}

async function pedir(ruta, cuerpo) {
  const opciones = cuerpo
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) }
    : {};
  const respuesta = await fetch(ruta, opciones);
  const datos = await respuesta.json();
  if (!respuesta.ok || datos.error) throw new Error(datos.error || `error ${respuesta.status}`);
  return datos;
}

function cargando(activo, mensaje = '') {
  $('estado-carga').textContent = mensaje;
  document.querySelectorAll('button').forEach((b) => { b.disabled = activo; });
}

function tarjeta(clave, valor, clase = '') {
  return `<div class="tarjeta"><div class="clave">${clave}</div>
          <div class="valor ${clase}">${valor}</div></div>`;
}

function pintarAvisos(destino, avisos) {
  const nodo = $(destino);
  nodo.innerHTML = (avisos || [])
    .map((a) => `<div class="mensaje-aviso">${a}</div>`)
    .join('');
}

// --------------------------------------------------------------------- gráfico
function dibujarCurva(curva, referencia) {
  const svg = $('curva');
  const ancho = 900;
  const alto = 320;
  const margen = { arriba: 14, abajo: 24, izq: 54, der: 12 };
  const series = [curva, referencia].filter((s) => s && s.length > 1);
  if (!series.length) { svg.innerHTML = ''; return; }

  const valores = series.flat().map((p) => p[1]);
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const rango = max - min || 1;
  const x = (i, n) => margen.izq + (i / Math.max(n - 1, 1)) * (ancho - margen.izq - margen.der);
  const y = (v) => margen.arriba + (1 - (v - min) / rango) * (alto - margen.arriba - margen.abajo);
  const ruta = (serie) => serie.map((p, i) => `${i ? 'L' : 'M'}${x(i, serie.length).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');

  const lineas = [];
  for (let k = 0; k <= 4; k += 1) {
    const v = min + (rango * k) / 4;
    const py = y(v).toFixed(1);
    lineas.push(`<line x1="${margen.izq}" y1="${py}" x2="${ancho - margen.der}" y2="${py}"
      stroke="currentColor" stroke-opacity=".12"/>`);
    lineas.push(`<text x="${margen.izq - 8}" y="${Number(py) + 4}" text-anchor="end"
      font-size="11" fill="currentColor" fill-opacity=".55">${v.toFixed(0)} €</text>`);
  }
  const primera = curva[0][0];
  const ultima = curva[curva.length - 1][0];
  lineas.push(`<text x="${margen.izq}" y="${alto - 6}" font-size="11" fill="currentColor"
    fill-opacity=".55">${primera}</text>`);
  lineas.push(`<text x="${ancho - margen.der}" y="${alto - 6}" text-anchor="end" font-size="11"
    fill="currentColor" fill-opacity=".55">${ultima}</text>`);

  const partes = [...lineas];
  if (referencia && referencia.length > 1) {
    partes.push(`<path d="${ruta(referencia)}" fill="none" stroke="var(--suave)"
      stroke-width="1.5" stroke-dasharray="5 4"/>`);
  }
  partes.push(`<path d="${ruta(curva)}" fill="none" stroke="var(--acento)" stroke-width="2.2"/>`);
  svg.innerHTML = partes.join('');
}

// -------------------------------------------------------------------- acciones
async function ejecutarBacktest() {
  cargando(true, 'Descargando datos y simulando…');
  try {
    const d = await pedir('/api/backtest', parametros());
    const m = d.metricas;
    const inicial = d.capital_inicial;
    $('tarjetas').innerHTML = [
      tarjeta('Capital final', eur(d.capital_final), signo(d.capital_final - inicial)),
      tarjeta('Rendimiento', pct(m.rendimiento_total), signo(m.rendimiento_total)),
      tarjeta('Anualizado', pct(m.cagr), signo(m.cagr)),
      tarjeta('Máxima caída', `−${pct(m.maxima_caida).replace('-', '')}`, 'negativo'),
      tarjeta('Sharpe', m.sharpe.toFixed(2), signo(m.sharpe)),
      tarjeta('Operaciones', m.operaciones),
      tarjeta('Aciertos', pct(m.acierto)),
      tarjeta('Costes', eur(m.costes), 'negativo'),
    ].join('');

    dibujarCurva(d.curva, d.referencia && d.referencia.curva);

    const avisos = (d.avisos || []).slice();
    if (d.referencia && d.capital_final <= d.referencia.capital_final) {
      avisos.push(`Comprar y mantener habría terminado en ${eur(d.referencia.capital_final)}: `
        + 'la estrategia automática no bate a no hacer nada en este periodo.');
    }
    if (m.costes > inicial * 0.1) {
      avisos.push(`Los costes (${eur(m.costes)}) se comen más del 10 % del capital inicial. `
        + 'Con cuentas pequeñas hay que operar poco y con comisiones bajas.');
    }
    pintarAvisos('avisos', avisos);

    const filas = (d.operaciones || []).map((o) => `<tr>
      <td>${o.simbolo}</td><td>${o.fecha_entrada}</td><td>${o.fecha_salida}</td>
      <td>${o.precio_entrada.toFixed(2)}</td><td>${o.precio_salida.toFixed(2)}</td>
      <td class="${signo(o.beneficio)}">${o.beneficio.toFixed(2)} €</td>
      <td>${o.motivo_salida}</td></tr>`).join('');
    $('tabla-operaciones').innerHTML = `<thead><tr><th>Activo</th><th>Entrada</th><th>Salida</th>
      <th>P. entrada</th><th>P. salida</th><th>Resultado</th><th>Motivo</th></tr></thead>
      <tbody>${filas || '<tr><td colspan="7">Sin operaciones</td></tr>'}</tbody>`;
    $('panel-resultado').hidden = false;
    $('panel-resultado').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    cargando(false, `Listo: ${d.estrategia} sobre ${d.simbolos.join(', ')}.`);
  } catch (e) {
    cargando(false, `Error: ${e.message}`);
  }
}

async function ejecutarMonteCarlo() {
  cargando(true, 'Simulando miles de caminos posibles…');
  try {
    const d = await pedir('/api/montecarlo', { ...parametros(), objetivo: 2.0, horizonte: 100, simulaciones: 8000 });
    const mc = d.montecarlo;
    $('tarjetas-mc').innerHTML = [
      tarjeta('P(duplicar)', pct(mc.prob_objetivo), mc.prob_objetivo > 0.3 ? 'positivo' : 'negativo'),
      tarjeta('P(acabar perdiendo)', pct(mc.prob_perdida), 'negativo'),
      tarjeta('P(ruina)', pct(mc.prob_ruina), 'negativo'),
      tarjeta('Resultado mediano', eur(mc.mediana)),
      tarjeta('Rango 5–95 %', `${eur(mc.p5)} – ${eur(mc.p95)}`),
      tarjeta('Caída media', `−${pct(mc.caida_media).replace('-', '')}`, 'negativo'),
    ].join('');
    $('barra-probabilidad').innerHTML =
      `<div class="barra"><div style="width:${(mc.prob_objetivo * 100).toFixed(1)}%"></div></div>
       <small>${pct(mc.prob_objetivo)} de los ${mc.simulaciones.toLocaleString('es-ES')} caminos
       simulados llegan a ${eur(mc.capital_inicial * 2)} en ${mc.horizonte} operaciones.</small>`;
    $('lectura-mc').textContent = mc.prob_objetivo < 0.1
      ? 'Con esta estrategia y este horizonte, duplicar el capital es muy improbable. '
        + 'Alargar el plazo o asumir más riesgo sube esa probabilidad, pero sube también la de perderlo todo.'
      : `Duplicar es posible pero no probable: ocurre en ${pct(mc.prob_objetivo)} de los caminos, `
        + `mientras que en ${pct(mc.prob_perdida)} se termina por debajo del capital inicial.`;
    $('panel-montecarlo').hidden = false;
    $('panel-montecarlo').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    cargando(false, 'Simulación terminada.');
  } catch (e) {
    cargando(false, `Error: ${e.message}`);
  }
}

async function ejecutarOptimizacion() {
  cargando(true, 'Buscando parámetros y validándolos fuera de muestra…');
  try {
    const d = await pedir('/api/optimizar', parametros());
    const filas = d.combinaciones.map((c) => `<tr>
      <td>${JSON.stringify(c.parametros)}</td>
      <td>${c.metrica_dentro.toFixed(2)}</td>
      <td class="${signo(c.metrica_fuera)}">${c.metrica_fuera.toFixed(2)}</td>
      <td>${eur(c.capital_final_fuera)}</td><td>${c.operaciones_fuera}</td></tr>`).join('');
    $('tabla-optimizacion').innerHTML = `<thead><tr><th>Parámetros</th><th>Dentro</th>
      <th>Fuera de muestra</th><th>Capital final</th><th>Ops.</th></tr></thead>
      <tbody>${filas || '<tr><td colspan="5">Sin combinaciones válidas</td></tr>'}</tbody>`;
    $('diagnostico').textContent = d.diagnostico;
    $('panel-optimizar').hidden = false;
    $('panel-optimizar').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    cargando(false, 'Optimización terminada.');
  } catch (e) {
    cargando(false, `Error: ${e.message}`);
  }
}

function pintarBot(d) {
  const rend = d.rendimiento ?? 0;
  $('tarjetas-bot').innerHTML = [
    tarjeta('Valor cartera', eur(d.valor_cartera), signo(rend)),
    tarjeta('Capital inicial', eur(d.capital_inicial)),
    tarjeta('Rendimiento', pct(rend), signo(rend)),
    tarjeta('Estrategia', d.estrategia || '—'),
    tarjeta('Estado', d.detenido ? 'DETENIDO' : 'activo', d.detenido ? 'negativo' : 'positivo'),
  ].join('');

  const posiciones = (d.cartera && d.cartera.posiciones) || [];
  $('tabla-posiciones').innerHTML = `<thead><tr><th>Activo</th><th>Unidades</th><th>Entrada</th>
    <th>Actual</th><th>Stop</th><th>P/L</th></tr></thead><tbody>${
    posiciones.map((p) => `<tr><td>${p.simbolo}</td><td>${p.unidades}</td>
      <td>${p.precio_entrada}</td><td>${p.precio_actual}</td><td>${p.stop ?? '—'}</td>
      <td class="${signo(p.pl_abierto)}">${p.pl_abierto.toFixed(2)} €</td></tr>`).join('')
    || '<tr><td colspan="6">Sin posiciones abiertas</td></tr>'}</tbody>`;

  $('diario').innerHTML = (d.diario || []).map((e) => `<li>
    <span class="tipo">${e.tipo}</span>${e.simbolo ? `<strong>${e.simbolo}</strong> ` : ''}
    ${e.mensaje}</li>`).join('') || '<li>Sin actividad todavía.</li>';
}

async function accionBot(ruta, mensaje) {
  cargando(true, mensaje);
  try {
    if (ruta !== '/api/estado') await pedir(ruta, parametros());
    pintarBot(await pedir('/api/estado'));
    cargando(false, 'Bot actualizado.');
  } catch (e) {
    cargando(false, `Error: ${e.message}`);
  }
}

async function inicio() {
  try {
    const d = await pedir('/api/estrategias');
    $('estrategia').innerHTML = d.estrategias
      .map((e) => `<option value="${e.nombre}" title="${e.descripcion}">${e.nombre}</option>`)
      .join('');
    $('version').textContent = `v${d.version}`;
    const config = await pedir('/api/config');
    $('capital').value = config.capital;
    $('simbolos').value = config.simbolos.join(',');
    $('estrategia').value = config.estrategia;
    $('dias').value = config.dias;
    $('comision').value = config.costes.comision_fija;
    $('proveedor').value = config.proveedor;
    pintarBot(await pedir('/api/estado'));
  } catch (e) {
    $('estado-carga').textContent = `No se pudo contactar con el servidor: ${e.message}`;
  }
}

$('btn-backtest').addEventListener('click', ejecutarBacktest);
$('btn-montecarlo').addEventListener('click', ejecutarMonteCarlo);
$('btn-optimizar').addEventListener('click', ejecutarOptimizacion);
$('btn-ciclo').addEventListener('click', () => accionBot('/api/ciclo', 'Ejecutando ciclo del bot…'));
$('btn-estado').addEventListener('click', () => accionBot('/api/estado', 'Consultando estado…'));
$('btn-reiniciar').addEventListener('click', () => {
  if (confirm('¿Reiniciar la cartera simulada al capital inicial? Se borra el historial.')) {
    accionBot('/api/reiniciar', 'Reiniciando cartera…');
  }
});
inicio();
