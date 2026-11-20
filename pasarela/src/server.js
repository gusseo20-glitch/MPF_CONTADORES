import express from 'express';
import crypto from 'node:crypto';
import { ErrorUsuario } from './orders.js';

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

const pagina = (titulo, cuerpo, extraHead = '') => `<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(titulo)}</title>${extraHead}
<style>
  body{font-family:system-ui,sans-serif;background:#f3f6f7;color:#1c2b30;margin:0;padding:16px}
  main{max-width:420px;margin:8vh auto;background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 12px #0001}
  h1{font-size:1.3rem;color:#006983;margin-top:0}
  label{display:block;margin:14px 0 4px;font-weight:600}
  input{width:100%;box-sizing:border-box;padding:10px;font-size:1rem;border:1px solid #b9c7cc;border-radius:8px}
  button{margin-top:20px;width:100%;padding:12px;font-size:1rem;border:0;border-radius:8px;background:#006983;color:#fff;cursor:pointer}
  .error{background:#fdecea;color:#8a1c12;padding:10px;border-radius:8px}
  .nota{color:#5b6b70;font-size:.9rem}
</style></head><body><main>${cuerpo}</main></body></html>`;

const formularioRecarga = (cfg, error = '', valores = {}) =>
  pagina(
    'Recargar crédito de impresión',
    `<h1>Recargar crédito de impresión</h1>
${error ? `<p class="error">${esc(error)}</p>` : ''}
<form method="post" action="/recarga">
  <label for="usuario">Usuario de MyQ</label>
  <input id="usuario" name="usuario" required maxlength="200" autocomplete="username" value="${esc(valores.usuario)}">
  <label for="importe">Importe (€)</label>
  <input id="importe" name="importe" required inputmode="decimal" placeholder="10,00" value="${esc(valores.importe)}">
  <p class="nota">Entre ${(cfg.importeMin / 100).toFixed(2)} € y ${(cfg.importeMax / 100).toFixed(2)} €. El pago se realiza en la página segura del banco.</p>
  <button type="submit">Pagar</button>
</form>`,
  );

const TEXTOS = {
  recargado: ['Recarga completada', 'Tu crédito ya está disponible.'],
  pagado: ['Pago recibido', 'Estamos añadiendo el crédito a tu cuenta. Esta página se actualiza sola.'],
  pendiente_pago: ['Esperando la confirmación del banco', 'Si has pagado, el crédito aparecerá en unos instantes. Esta página se actualiza sola.'],
  denegado: ['Pago no realizado', 'El banco no ha autorizado el pago. No se ha cobrado nada.'],
  caducado: ['Pago no completado', 'El pago no se llegó a realizar. No se ha cobrado nada.'],
  fallido: ['Recarga no iniciada', 'No se pudo preparar la recarga. No se ha cobrado nada.'],
  revision_manual: ['Pago recibido, recarga en revisión', 'Hemos recibido tu pago y estamos revisando la recarga. Contacta con soporte indicando tu número de pedido.'],
};

export function crearApp({ cfg, db, pedidos }) {
  const app = express();
  app.disable('x-powered-by');
  app.set('trust proxy', 1);
  app.use(express.urlencoded({ extended: false, limit: '64kb' }));

  app.get('/salud', async (_req, res) => {
    try {
      await db.query('SELECT 1');
      res.json({ ok: true });
    } catch {
      res.status(503).json({ ok: false });
    }
  });

  app.get('/', (_req, res) => res.send(formularioRecarga(cfg)));

  app.post('/recarga', async (req, res, next) => {
    try {
      const { formulario } = await pedidos.iniciar(req.body);
      const campos = Object.entries(formulario.campos)
        .map(([k, v]) => `<input type="hidden" name="${esc(k)}" value="${esc(v)}">`)
        .join('');
      res.send(
        pagina(
          'Redirigiendo al banco…',
          `<h1>Redirigiendo al banco…</h1>
<form id="f" method="post" action="${esc(formulario.url)}">${campos}
<noscript><button type="submit">Continuar al pago</button></noscript></form>
<script>document.getElementById('f').submit()</script>`,
        ),
      );
    } catch (e) {
      if (e instanceof ErrorUsuario) return res.status(400).send(formularioRecarga(cfg, e.message, req.body));
      next(e);
    }
  });

  // Página a la que Redsys devuelve al usuario. Solo muestra lo que diga la
  // base de datos: volver aquí no acredita ningún pago.
  app.get('/recarga/:token', async (req, res, next) => {
    try {
      if (!/^[0-9a-f-]{36}$/i.test(req.params.token)) return res.status(404).send(pagina('No encontrado', '<h1>Pedido no encontrado</h1>'));
      const { rows } = await db.query('SELECT numero_pedido, estado, importe_centimos FROM pedidos WHERE token = $1', [req.params.token]);
      const p = rows[0];
      if (!p) return res.status(404).send(pagina('No encontrado', '<h1>Pedido no encontrado</h1>'));
      const [titulo, texto] = TEXTOS[p.estado] || TEXTOS.pendiente_pago;
      const enCurso = ['pendiente_pago', 'pagado', 'creado'].includes(p.estado);
      res.send(
        pagina(
          titulo,
          `<h1>${esc(titulo)}</h1><p>${esc(texto)}</p>
<p class="nota">Pedido ${esc(p.numero_pedido)} · ${(p.importe_centimos / 100).toFixed(2)} €</p>
${enCurso ? '' : '<p><a href="/">Hacer otra recarga</a></p>'}`,
          enCurso ? '<meta http-equiv="refresh" content="5">' : '',
        ),
      );
    } catch (e) {
      next(e);
    }
  });

  // Notificación de servidor de Redsys.
  // 200 = recibida (Redsys no reintenta); 500 = error nuestro (que reintente).
  app.post('/redsys/notificacion', async (req, res) => {
    let r;
    try {
      r = await pedidos.notificar(req.body);
    } catch (e) {
      const firma = /firma|incompleta|ilegible|admitida|sin número/i.test(e.message);
      if (!firma) console.error('[notificacion] error:', e);
      return res.status(firma ? 400 : 500).send('KO');
    }
    res.status(r.ok ? 200 : 400).send(r.ok ? 'OK' : 'KO');
    // La recarga se intenta ya; si falla, la tarea periódica la reintenta.
    if (r.motivo === 'pagado') pedidos.confirmarUno(r.id).catch((e) => console.error('[confirmar] error:', e));
  });

  // --- Soporte ---
  const admin = express.Router();
  admin.use((req, res, next) => {
    const dado = Buffer.from(String(req.headers.authorization || '').replace(/^Bearer\s+/i, ''));
    const bueno = Buffer.from(cfg.adminToken);
    if (dado.length !== bueno.length || !crypto.timingSafeEqual(dado, bueno)) return res.status(401).json({ error: 'no autorizado' });
    next();
  });
  admin.get('/pedidos', async (req, res, next) => {
    try {
      const { estado, usuario, pedido } = req.query;
      const { rows } = await db.query(
        `SELECT id, numero_pedido, usuario_myq, importe_centimos, estado, redsys_respuesta, redsys_autorizacion,
                myq_payment_id, intentos, ultimo_error, creado_en, pagado_en, recargado_en
         FROM pedidos
         WHERE ($1::text IS NULL OR estado = $1) AND ($2::text IS NULL OR usuario_myq = $2)
           AND ($3::text IS NULL OR numero_pedido = $3)
         ORDER BY id DESC LIMIT 200`,
        [estado || null, usuario || null, pedido || null],
      );
      res.json(rows);
    } catch (e) {
      next(e);
    }
  });
  admin.get('/pedidos/:id/eventos', async (req, res, next) => {
    try {
      if (!/^\d+$/.test(req.params.id)) return res.status(400).json({ error: 'id no válido' });
      const { rows } = await db.query('SELECT tipo, detalle, creado_en FROM eventos WHERE pedido_id = $1 ORDER BY id', [req.params.id]);
      res.json(rows);
    } catch (e) {
      next(e);
    }
  });
  admin.post('/pedidos/:id/reintentar', async (req, res, next) => {
    try {
      if (!/^\d+$/.test(req.params.id)) return res.status(400).json({ error: 'id no válido' });
      const ok = await pedidos.reintentarManual(req.params.id);
      res.status(ok ? 200 : 409).json({ ok });
    } catch (e) {
      next(e);
    }
  });
  app.use('/admin', admin);

  app.use((err, _req, res, _next) => {
    console.error('[http] error:', err);
    res.status(500).send(pagina('Error', '<h1>Ha ocurrido un error</h1><p>Inténtalo de nuevo en unos minutos.</p>'));
  });
  return app;
}
