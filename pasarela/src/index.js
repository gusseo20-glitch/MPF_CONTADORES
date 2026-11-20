import { cargarConfig } from './config.js';
import { crearDb } from './db.js';
import { crearClienteMyq } from './myq.js';
import { crearAlertas } from './alerts.js';
import { crearPedidos } from './orders.js';
import { crearApp } from './server.js';

const cfg = cargarConfig();
const db = crearDb(cfg.databaseUrl);
await db.migrar();

const alertar = crearAlertas(cfg.alertWebhookUrl);
const pedidos = crearPedidos({ cfg, db, myq: crearClienteMyq(cfg.myq), alertar });
const app = crearApp({ cfg, db, pedidos });

const servidor = app.listen(cfg.port, () => console.log(`Pasarela escuchando en el puerto ${cfg.port}`));

// Tarea periódica: reintenta recargas pendientes y caduca pagos abandonados.
let enCurso = false;
const temporizador = setInterval(async () => {
  if (enCurso) return;
  enCurso = true;
  try {
    await pedidos.tick();
  } catch (e) {
    console.error('[worker] error:', e);
  } finally {
    enCurso = false;
  }
}, cfg.workerIntervaloMs);

for (const senal of ['SIGTERM', 'SIGINT']) {
  process.on(senal, () => {
    clearInterval(temporizador);
    servidor.close(() => db.cerrar().finally(() => process.exit(0)));
  });
}
