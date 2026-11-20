// Las alertas van siempre al log y, si está configurado, a un webhook.
export function crearAlertas(webhookUrl) {
  return async function alertar(titulo, detalle = {}) {
    console.error(`[ALERTA] ${titulo}`, JSON.stringify(detalle));
    if (!webhookUrl) return;
    try {
      await fetch(webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: `[Pasarela MyQ] ${titulo}`, titulo, detalle }),
        signal: AbortSignal.timeout(10000),
      });
    } catch (e) {
      console.error('[ALERTA] no se pudo enviar al webhook:', e.message);
    }
  };
}
