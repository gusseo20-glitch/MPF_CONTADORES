// Ciclo de vida de un pedido de recarga. La base de datos es la fuente de
// verdad: cada cambio de estado es un UPDATE condicionado al estado anterior,
// de modo que repetir una operación nunca recarga ni cobra dos veces.
import { crearFormulario, verificarNotificacion, estaAutorizado } from './redsys.js';

export class ErrorUsuario extends Error {}

// "10", "10,5" o "10.50" -> céntimos. Devuelve null si no es un importe válido.
export function aCentimos(texto) {
  const m = /^(\d{1,5})(?:[.,](\d{1,2}))?$/.exec(String(texto ?? '').trim());
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] || '').padEnd(2, '0'));
}

export function crearPedidos({ cfg, db, myq, alertar }) {
  const evento = (c, pedidoId, tipo, detalle) =>
    c.query('INSERT INTO eventos (pedido_id, tipo, detalle) VALUES ($1, $2, $3)', [
      pedidoId,
      tipo,
      detalle ? JSON.stringify(detalle) : null,
    ]);

  // 1. El usuario pide recargar: se guarda el pedido, se deja la recarga
  //    pendiente en MyQ y se devuelve el formulario firmado para Redsys.
  //    Si MyQ falla aquí, no se envía a pagar: nunca se cobra sin poder recargar.
  async function iniciar({ usuario, importe }) {
    usuario = String(usuario ?? '').trim();
    if (!usuario || usuario.length > 200) throw new ErrorUsuario('Indica tu usuario de MyQ.');
    const centimos = aCentimos(importe);
    if (centimos === null || centimos < cfg.importeMin || centimos > cfg.importeMax) {
      throw new ErrorUsuario(
        `El importe debe estar entre ${(cfg.importeMin / 100).toFixed(2)} € y ${(cfg.importeMax / 100).toFixed(2)} €.`,
      );
    }

    const { rows } = await db.query(
      `INSERT INTO pedidos (usuario_myq, importe_centimos, estado) VALUES ($1, $2, 'creado') RETURNING *`,
      [usuario, centimos],
    );
    const pedido = rows[0];
    await evento(db, pedido.id, 'creado', { usuario, centimos });

    let userId, paymentId;
    try {
      userId = await myq.buscarUsuario(usuario);
      if (userId !== null) {
        paymentId = await myq.crearPago(userId, centimos, `Redsys ${pedido.numero_pedido}`);
      }
    } catch (e) {
      await db.query(
        `UPDATE pedidos SET estado = 'fallido', ultimo_error = $2, actualizado_en = now() WHERE id = $1`,
        [pedido.id, e.message],
      );
      await evento(db, pedido.id, 'fallo_preparacion', { error: e.message });
      await alertar('MyQ no disponible al preparar una recarga (no se ha cobrado)', {
        pedido: pedido.numero_pedido,
        error: e.message,
      });
      throw new ErrorUsuario('El sistema de impresión no está disponible ahora. No se ha cobrado nada; inténtalo más tarde.');
    }
    if (userId === null) {
      await db.query(
        `UPDATE pedidos SET estado = 'fallido', ultimo_error = 'usuario no encontrado', actualizado_en = now() WHERE id = $1`,
        [pedido.id],
      );
      throw new ErrorUsuario('No existe ese usuario en MyQ.');
    }

    await db.query(
      `UPDATE pedidos SET estado = 'pendiente_pago', myq_user_id = $2, myq_payment_id = $3, actualizado_en = now()
       WHERE id = $1`,
      [pedido.id, userId, paymentId],
    );
    await evento(db, pedido.id, 'enviado_a_redsys', { myq_user_id: userId, myq_payment_id: paymentId });

    return {
      pedido: { ...pedido, estado: 'pendiente_pago' },
      formulario: crearFormulario(cfg.redsys, {
        numeroPedido: pedido.numero_pedido,
        centimos,
        urlNotificacion: `${cfg.publicUrl}/redsys/notificacion`,
        urlOk: `${cfg.publicUrl}/recarga/${pedido.token}`,
        urlKo: `${cfg.publicUrl}/recarga/${pedido.token}`,
      }),
    };
  }

  // 2. Notificación de servidor de Redsys. Es lo único que acredita un pago.
  //    Devuelve { ok, motivo }. Lanza si la firma no es válida.
  async function notificar(cuerpo) {
    let p;
    try {
      p = verificarNotificacion(cfg.redsys, cuerpo);
    } catch (e) {
      await alertar('Notificación de Redsys rechazada', { error: e.message });
      throw e;
    }
    const numero = p.Ds_Order;
    const autorizado = estaAutorizado(p);

    const resultado = await db.tx(async (c) => {
      const { rows } = await c.query('SELECT * FROM pedidos WHERE numero_pedido = $1 FOR UPDATE', [numero]);
      const pedido = rows[0];
      if (!pedido) return { ok: false, motivo: 'pedido_desconocido', alerta: { numero } };

      await evento(c, pedido.id, 'notificacion_redsys', p);

      const coincide =
        String(p.Ds_Amount) === String(pedido.importe_centimos) &&
        String(p.Ds_Currency) === cfg.redsys.currency &&
        String(p.Ds_MerchantCode) === cfg.redsys.merchantCode &&
        Number(p.Ds_Terminal) === Number(cfg.redsys.terminal);
      if (!coincide) {
        return { ok: false, motivo: 'datos_no_coinciden', alerta: { numero, recibido: p } };
      }

      if (!autorizado) {
        // Una denegación nunca deshace un pago ya registrado.
        await c.query(
          `UPDATE pedidos SET estado = 'denegado', redsys_respuesta = $2, actualizado_en = now()
           WHERE id = $1 AND estado IN ('pendiente_pago', 'caducado')`,
          [pedido.id, String(p.Ds_Response ?? '')],
        );
        return { ok: true, motivo: 'denegado' };
      }

      if (['pagado', 'recargado', 'revision_manual'].includes(pedido.estado)) {
        return { ok: true, motivo: 'duplicada' }; // Redsys repite notificaciones: no hacer nada
      }
      if (!pedido.myq_payment_id) {
        // Cobrado sin recarga preparada: no debería ocurrir; lo resuelve una persona.
        await c.query(
          `UPDATE pedidos SET estado = 'revision_manual', pagado_en = now(), redsys_respuesta = $2,
             redsys_autorizacion = $3, actualizado_en = now() WHERE id = $1`,
          [pedido.id, String(p.Ds_Response), p.Ds_AuthorisationCode ?? null],
        );
        return { ok: true, motivo: 'pagado_sin_recarga', alerta: { numero } };
      }
      // Un pago autorizado se acepta aunque el pedido figurase caducado o
      // denegado: el dinero se ha cobrado y hay que entregar el crédito.
      await c.query(
        `UPDATE pedidos SET estado = 'pagado', pagado_en = now(), proximo_intento = now(),
           redsys_respuesta = $2, redsys_autorizacion = $3, actualizado_en = now()
         WHERE id = $1`,
        [pedido.id, String(p.Ds_Response), p.Ds_AuthorisationCode ?? null],
      );
      return { ok: true, motivo: 'pagado', id: pedido.id };
    });

    if (resultado.alerta) await alertar(`Notificación de Redsys anómala: ${resultado.motivo}`, resultado.alerta);
    return resultado;
  }

  // 3. Confirma en MyQ un pedido pagado. La fila queda bloqueada durante la
  //    llamada, así que dos procesos nunca confirman el mismo pedido a la vez.
  //    Con id: ese pedido concreto (espera si otro proceso lo tiene bloqueado).
  //    Sin id: el siguiente al que le toque, saltando los que estén bloqueados.
  async function confirmarUno(id = null) {
    let alerta = null;
    const hecho = await db.tx(async (c) => {
      const { rows } = await c.query(
        `SELECT * FROM pedidos
         WHERE estado = 'pagado' AND (($1::bigint IS NULL AND proximo_intento <= now()) OR id = $1::bigint)
         ORDER BY proximo_intento LIMIT 1 FOR UPDATE ${id === null ? 'SKIP LOCKED' : ''}`,
        [id],
      );
      const pedido = rows[0];
      if (!pedido) return null;
      try {
        const r = await myq.confirmarPago(pedido.myq_payment_id);
        await c.query(
          `UPDATE pedidos SET estado = 'recargado', recargado_en = now(), intentos = intentos + 1,
             ultimo_error = NULL, proximo_intento = NULL, actualizado_en = now() WHERE id = $1`,
          [pedido.id],
        );
        await evento(c, pedido.id, 'recargado', r);
        return 'recargado';
      } catch (e) {
        const intentos = pedido.intentos + 1;
        const agotado = Date.now() - new Date(pedido.pagado_en).getTime() > cfg.limiteReintentosHoras * 3600e3;
        // Espera creciente: 30 s, 1 min, 2 min... hasta un máximo de 30 min
        const esperaSeg = Math.min(30 * 2 ** (intentos - 1), 1800);
        await c.query(
          `UPDATE pedidos SET estado = $2, intentos = $3, ultimo_error = $4,
             proximo_intento = now() + make_interval(secs => $5), actualizado_en = now() WHERE id = $1`,
          [pedido.id, agotado ? 'revision_manual' : 'pagado', intentos, e.message, esperaSeg],
        );
        await evento(c, pedido.id, 'fallo_recarga', { intento: intentos, error: e.message });
        if (agotado) {
          alerta = ['Pago cobrado sin recargar: requiere revisión manual', { pedido: pedido.numero_pedido, error: e.message }];
        } else if (intentos === 3) {
          alerta = ['La recarga en MyQ está fallando (se sigue reintentando)', { pedido: pedido.numero_pedido, error: e.message }];
        }
        return 'fallo';
      }
    });
    if (alerta) await alertar(...alerta);
    return hecho;
  }

  // Tarea periódica: confirma lo pendiente y da por abandonados los pagos sin completar.
  async function tick() {
    let n = 0;
    while (n < 50 && (await confirmarUno())) n++;
    await db.query(
      `UPDATE pedidos SET estado = 'caducado', actualizado_en = now()
       WHERE estado IN ('creado', 'pendiente_pago') AND creado_en < now() - make_interval(mins => $1)`,
      [cfg.caducidadMinutos],
    );
    return n;
  }

  // Soporte: vuelve a poner en cola un pedido en revisión manual.
  async function reintentarManual(id) {
    const { rowCount } = await db.query(
      `UPDATE pedidos SET estado = 'pagado', proximo_intento = now(), pagado_en = now(), actualizado_en = now()
       WHERE id = $1 AND estado = 'revision_manual' AND myq_payment_id IS NOT NULL`,
      [id],
    );
    if (!rowCount) return false;
    await evento(db, id, 'reintento_manual', null);
    await confirmarUno(id);
    return true;
  }

  return { iniciar, notificar, confirmarUno, tick, reintentarManual };
}
