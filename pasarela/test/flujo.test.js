// Pruebas de extremo a extremo: PostgreSQL real, MyQ simulado y notificaciones
// firmadas como las firma Redsys.
// Requiere TEST_DATABASE_URL apuntando a una base de datos vacía de pruebas.
import test, { before, after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { crearDb } from '../src/db.js';
import { crearClienteMyq } from '../src/myq.js';
import { crearPedidos } from '../src/orders.js';
import { crearApp } from '../src/server.js';
import { firmar } from '../src/redsys.js';

const DB_URL = process.env.TEST_DATABASE_URL;
const omitir = !DB_URL && 'define TEST_DATABASE_URL para ejecutar estas pruebas';
const key = 'sq7HjrUOBfKmC576ILgskD5srU870gJ7';

let db, app, servidor, base, pedidos, myqFalso, alertas;

// MyQ simulado: cuenta las llamadas y permite provocar fallos.
function crearMyqFalso() {
  const estado = { caido: false, tokens: 0, pagos: new Map(), saldo: new Map(), commits: 0, sig: 500 };
  const srv = http.createServer((req, res) => {
    let cuerpo = '';
    req.on('data', (d) => (cuerpo += d));
    req.on('end', () => {
      const enviar = (codigo, obj) => {
        res.writeHead(codigo, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(obj));
      };
      if (estado.caido) return enviar(503, { error: 'caido' });
      const json = cuerpo ? JSON.parse(cuerpo) : {};
      if (req.method === 'POST' && req.url === '/api/auth/token') {
        estado.tokens++;
        if (json.client_secret !== 'secreto') return enviar(401, {});
        return enviar(200, { access_token: 'tok', expires_in: 1800 });
      }
      if (req.headers.authorization !== 'Bearer tok') return enviar(401, {});
      if (req.method === 'GET' && req.url.startsWith('/api/v3/users')) {
        const u = new URL(req.url, 'http://x').searchParams.get('username');
        return enviar(200, u === 'ana' ? [{ id: 1176, username: 'ana' }] : []);
      }
      if (req.method === 'POST' && req.url === '/api/v3/rechargeProviders/external/payments') {
        const id = ++estado.sig;
        estado.pagos.set(id, { userId: json.userId, amount: json.params.amount, estado: 'created' });
        return enviar(201, { id });
      }
      const m = /^\/api\/v3\/rechargeProviders\/external\/payments\/(\d+)\/commit$/.exec(req.url);
      if (req.method === 'POST' && m) {
        const pago = estado.pagos.get(Number(m[1]));
        if (!pago) return enviar(404, {});
        if (pago.estado === 'completed') return enviar(409, { error: 'ya confirmado' });
        pago.estado = 'completed';
        estado.commits++;
        estado.saldo.set(pago.userId, (estado.saldo.get(pago.userId) || 0) + pago.amount);
        return enviar(200, { amount: pago.amount });
      }
      enviar(404, {});
    });
  });
  return { estado, srv };
}

const escuchar = (srv) => new Promise((ok) => srv.listen(0, '127.0.0.1', () => ok(srv.address().port)));

before(async () => {
  if (omitir) return;
  db = crearDb(DB_URL);
  await db.query('DROP TABLE IF EXISTS eventos, pedidos; DROP SEQUENCE IF EXISTS pedidos_numero_seq');
  await db.migrar();
  myqFalso = crearMyqFalso();
  const puertoMyq = await escuchar(myqFalso.srv);
  const cfg = {
    publicUrl: 'https://recargas.test',
    adminToken: 'admin-secreto',
    importeMin: 100,
    importeMax: 10000,
    caducidadMinutos: 120,
    limiteReintentosHoras: 24,
    redsys: { url: 'https://tpv.test/pago', merchantCode: '999008881', terminal: '1', key, merchantName: 'T', currency: '978', signatureVersion: 'HMAC_SHA512_V2' },
    myq: { apiUrl: `http://127.0.0.1:${puertoMyq}/api`, version: 'v3', clientId: 'app', clientSecret: 'secreto', scope: 'credit users', provider: 'external', timeoutMs: 2000 },
  };
  alertas = [];
  pedidos = crearPedidos({ cfg, db, myq: crearClienteMyq(cfg.myq), alertar: async (t, d) => void alertas.push([t, d]) });
  app = crearApp({ cfg, db, pedidos });
  servidor = http.createServer(app);
  base = `http://127.0.0.1:${await escuchar(servidor)}`;
});

after(async () => {
  if (omitir) return;
  servidor.close();
  myqFalso.srv.close();
  await db.cerrar();
});

beforeEach(async () => {
  if (omitir) return;
  await db.query('TRUNCATE eventos, pedidos RESTART IDENTITY');
  Object.assign(myqFalso.estado, { caido: false, commits: 0 });
  myqFalso.estado.pagos.clear();
  myqFalso.estado.saldo.clear();
  alertas.length = 0;
});

const post = (ruta, datos, cabeceras = {}) =>
  fetch(base + ruta, { method: 'POST', body: new URLSearchParams(datos), headers: cabeceras });

async function iniciar(importe = '10,50', usuario = 'ana') {
  const res = await post('/recarga', { usuario, importe });
  const html = await res.text();
  const campo = (n) => new RegExp(`name="${n}" value="([^"]*)"`).exec(html)?.[1];
  const datos = campo('Ds_MerchantParameters');
  return { res, html, params: datos && JSON.parse(Buffer.from(datos, 'base64').toString()), campo };
}

function notif(params, { version = 'HMAC_SHA512_V2', clave = key } = {}) {
  const datos = Buffer.from(JSON.stringify(params)).toString('base64');
  return { Ds_SignatureVersion: version, Ds_MerchantParameters: datos, Ds_Signature: firmar(version, clave, params.Ds_Order, datos) };
}

const ok = (pedido, extra = {}) => ({
  Ds_Order: pedido, Ds_Amount: '1050', Ds_Currency: '978', Ds_MerchantCode: '999008881', Ds_Terminal: '001',
  Ds_Response: '0000', Ds_AuthorisationCode: '123456', ...extra,
});

const fila = async (numero) => (await db.query('SELECT * FROM pedidos WHERE numero_pedido = $1', [numero])).rows[0];

// La confirmación tras la notificación es asíncrona: espera a que el pedido salga de un estado.
async function esperarEstado(numero, estado) {
  for (let i = 0; i < 100; i++) {
    const f = await fila(numero);
    if (f.estado === estado) return f;
    await new Promise((r) => setTimeout(r, 20));
  }
  assert.fail(`el pedido ${numero} no llegó a ${estado}: está en ${(await fila(numero)).estado}`);
}

test('flujo correcto: pago autorizado suma el crédito una sola vez', { skip: omitir }, async () => {
  const { res, params, campo } = await iniciar();
  assert.equal(res.status, 200);
  assert.equal(campo('Ds_SignatureVersion'), 'HMAC_SHA512_V2');
  assert.equal(params.DS_MERCHANT_AMOUNT, '1050');
  assert.match(params.DS_MERCHANT_ORDER, /^\d{12}$/);
  assert.equal(params.DS_MERCHANT_MERCHANTURL, 'https://recargas.test/redsys/notificacion');
  const numero = params.DS_MERCHANT_ORDER;
  assert.equal((await fila(numero)).estado, 'pendiente_pago');
  assert.equal(myqFalso.estado.saldo.get(1176), undefined, 'sin pago no hay crédito');

  const r = await post('/redsys/notificacion', notif(ok(numero)));
  assert.equal(r.status, 200);
  const f = await esperarEstado(numero, 'recargado');
  assert.equal(f.redsys_autorizacion, '123456');
  assert.equal(myqFalso.estado.saldo.get(1176), 10.5);
  assert.equal(myqFalso.estado.commits, 1);
});

test('notificación repetida (también en paralelo) no recarga dos veces', { skip: omitir }, async () => {
  const numero = (await iniciar()).params.DS_MERCHANT_ORDER;
  const n = notif(ok(numero));
  const rs = await Promise.all(Array.from({ length: 8 }, () => post('/redsys/notificacion', n)));
  assert.deepEqual(rs.map((r) => r.status), Array(8).fill(200));
  await esperarEstado(numero, 'recargado');
  assert.equal((await post('/redsys/notificacion', n)).status, 200);
  await pedidos.tick();
  assert.equal(myqFalso.estado.commits, 1);
  assert.equal(myqFalso.estado.saldo.get(1176), 10.5);
});

test('firma falsa: se rechaza y no se recarga', { skip: omitir }, async () => {
  const numero = (await iniciar()).params.DS_MERCHANT_ORDER;
  const r = await post('/redsys/notificacion', notif(ok(numero), { clave: 'Mk9m98IfEblmPfrpsawt7BmxObt98Jev' }));
  assert.equal(r.status, 400);
  assert.equal((await fila(numero)).estado, 'pendiente_pago');
  assert.equal(myqFalso.estado.commits, 0);
  assert.equal(alertas.length, 1);
});

test('importe manipulado: firma válida pero importe distinto no recarga', { skip: omitir }, async () => {
  const numero = (await iniciar()).params.DS_MERCHANT_ORDER;
  const r = await post('/redsys/notificacion', notif(ok(numero, { Ds_Amount: '1' })));
  assert.equal(r.status, 400);
  assert.equal((await fila(numero)).estado, 'pendiente_pago');
  assert.equal(myqFalso.estado.commits, 0);
  assert.match(alertas[0][0], /datos_no_coinciden/);
});

test('pago denegado: no recarga; una denegación tardía no deshace un pago', { skip: omitir }, async () => {
  const a = (await iniciar()).params.DS_MERCHANT_ORDER;
  assert.equal((await post('/redsys/notificacion', notif(ok(a, { Ds_Response: '0190' })))).status, 200);
  assert.equal((await fila(a)).estado, 'denegado');
  assert.equal(myqFalso.estado.commits, 0);

  const b = (await iniciar()).params.DS_MERCHANT_ORDER;
  await post('/redsys/notificacion', notif(ok(b)));
  await esperarEstado(b, 'recargado');
  await post('/redsys/notificacion', notif(ok(b, { Ds_Response: '0190' })));
  assert.equal((await fila(b)).estado, 'recargado');
});

test('MyQ caído tras el cobro: queda pendiente y se recarga al reintentar', { skip: omitir }, async () => {
  const numero = (await iniciar()).params.DS_MERCHANT_ORDER;
  myqFalso.estado.caido = true;
  assert.equal((await post('/redsys/notificacion', notif(ok(numero)))).status, 200);
  for (let i = 0; i < 100 && (await fila(numero)).intentos < 1; i++) await new Promise((r) => setTimeout(r, 20));
  let f = await fila(numero);
  assert.equal(f.estado, 'pagado');
  assert.equal(f.intentos, 1);
  assert.match(f.ultimo_error, /503/);
  assert.ok(new Date(f.proximo_intento) > new Date(), 'el reintento se programa para más tarde');

  // Aún no toca reintentar: la tarea periódica no hace nada
  assert.equal(await pedidos.tick(), 0);

  myqFalso.estado.caido = false;
  await db.query(`UPDATE pedidos SET proximo_intento = now() WHERE numero_pedido = $1`, [numero]);
  assert.equal(await pedidos.tick(), 1);
  f = await fila(numero);
  assert.equal(f.estado, 'recargado');
  assert.equal(myqFalso.estado.saldo.get(1176), 10.5);
  assert.equal(myqFalso.estado.commits, 1);
});

test('reintentos agotados: pasa a revisión manual con alerta y soporte puede relanzarlo', { skip: omitir }, async () => {
  const numero = (await iniciar()).params.DS_MERCHANT_ORDER;
  myqFalso.estado.caido = true;
  await post('/redsys/notificacion', notif(ok(numero)));
  for (let i = 0; i < 100 && (await fila(numero)).intentos < 1; i++) await new Promise((r) => setTimeout(r, 20));
  await db.query(`UPDATE pedidos SET pagado_en = now() - interval '25 hours', proximo_intento = now() WHERE numero_pedido = $1`, [numero]);
  await pedidos.tick();
  const f = await fila(numero);
  assert.equal(f.estado, 'revision_manual');
  assert.ok(alertas.some(([t]) => /revisión manual/.test(t)));

  const sinToken = await post(`/admin/pedidos/${f.id}/reintentar`, {});
  assert.equal(sinToken.status, 401);
  myqFalso.estado.caido = false;
  const con = await post(`/admin/pedidos/${f.id}/reintentar`, {}, { Authorization: 'Bearer admin-secreto' });
  assert.equal(con.status, 200);
  assert.equal((await fila(numero)).estado, 'recargado');
  assert.equal(myqFalso.estado.commits, 1);
});

test('MyQ caído antes del pago: no se envía al usuario a pagar', { skip: omitir }, async () => {
  myqFalso.estado.caido = true;
  const { res, html, params } = await iniciar();
  assert.equal(res.status, 400);
  assert.equal(params, undefined, 'no hay formulario hacia Redsys');
  assert.match(html, /No se ha cobrado nada/);
  assert.equal((await db.query('SELECT estado FROM pedidos')).rows[0].estado, 'fallido');
});

test('entradas no válidas: usuario inexistente e importes fuera de rango', { skip: omitir }, async () => {
  assert.equal((await iniciar('10', 'nadie')).res.status, 400);
  for (const importe of ['0,50', '100,01', 'abc', '-5', '']) {
    const { res, params } = await iniciar(importe);
    assert.equal(res.status, 400, importe);
    assert.equal(params, undefined);
  }
  assert.equal(myqFalso.estado.pagos.size, 0);
});

test('pago autorizado que llega tras caducar el pedido también se recarga', { skip: omitir }, async () => {
  const numero = (await iniciar()).params.DS_MERCHANT_ORDER;
  await db.query(`UPDATE pedidos SET creado_en = now() - interval '3 hours'`);
  await pedidos.tick();
  assert.equal((await fila(numero)).estado, 'caducado');
  await post('/redsys/notificacion', notif(ok(numero)));
  await esperarEstado(numero, 'recargado');
  assert.equal(myqFalso.estado.commits, 1);
});

test('la página de resultado refleja la base de datos y no acredita pagos', { skip: omitir }, async () => {
  const numero = (await iniciar()).params.DS_MERCHANT_ORDER;
  const { token } = await fila(numero);
  let html = await (await fetch(`${base}/recarga/${token}`)).text();
  assert.match(html, /Esperando la confirmación del banco/);
  assert.equal((await fila(numero)).estado, 'pendiente_pago');
  await post('/redsys/notificacion', notif(ok(numero)));
  await esperarEstado(numero, 'recargado');
  html = await (await fetch(`${base}/recarga/${token}`)).text();
  assert.match(html, /Recarga completada/);
  assert.equal((await fetch(`${base}/recarga/00000000-0000-0000-0000-000000000000`)).status, 404);
});

test('listado de soporte: protegido por token y con historial de eventos', { skip: omitir }, async () => {
  const numero = (await iniciar()).params.DS_MERCHANT_ORDER;
  await post('/redsys/notificacion', notif(ok(numero)));
  const f = await esperarEstado(numero, 'recargado');
  assert.equal((await fetch(`${base}/admin/pedidos`)).status, 401);
  const h = { Authorization: 'Bearer admin-secreto' };
  const lista = await (await fetch(`${base}/admin/pedidos?estado=recargado`, { headers: h })).json();
  assert.equal(lista.length, 1);
  assert.equal(lista[0].numero_pedido, numero);
  const eventos = await (await fetch(`${base}/admin/pedidos/${f.id}/eventos`, { headers: h })).json();
  assert.deepEqual(eventos.map((e) => e.tipo), ['creado', 'enviado_a_redsys', 'notificacion_redsys', 'recargado']);
});
