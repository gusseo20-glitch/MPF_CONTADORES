// Cliente de la API REST de MyQ X para recargas con "External Payment Provider".
export class MyqError extends Error {
  constructor(mensaje, status) {
    super(mensaje);
    this.status = status;
  }
}

export function crearClienteMyq(cfg) {
  let token = null; // { valor, caduca }

  async function pedir(metodo, ruta, { cuerpo, auth = true } = {}) {
    const cabeceras = { Accept: 'application/json' };
    if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json';
    if (auth) cabeceras.Authorization = `Bearer ${await obtenerToken()}`;
    let res;
    try {
      res = await fetch(`${cfg.apiUrl}${ruta}`, {
        method: metodo,
        headers: cabeceras,
        body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
        signal: AbortSignal.timeout(cfg.timeoutMs),
      });
    } catch (e) {
      throw new MyqError(`MyQ no responde (${metodo} ${ruta}): ${e.message}`);
    }
    const texto = await res.text();
    if (res.status === 401 && auth) token = null; // el siguiente intento pedirá token nuevo
    if (!res.ok) {
      throw new MyqError(`MyQ respondió ${res.status} a ${metodo} ${ruta}: ${texto.slice(0, 300)}`, res.status);
    }
    try {
      return texto ? JSON.parse(texto) : {};
    } catch {
      throw new MyqError(`Respuesta de MyQ no es JSON (${metodo} ${ruta})`, res.status);
    }
  }

  async function obtenerToken() {
    if (token && token.caduca > Date.now()) return token.valor;
    const r = await pedir('POST', '/auth/token', {
      auth: false,
      cuerpo: {
        grant_type: 'client_credentials',
        client_id: cfg.clientId,
        client_secret: cfg.clientSecret,
        scope: cfg.scope,
      },
    });
    if (!r.access_token) throw new MyqError('MyQ no devolvió access_token');
    const segundos = Number(r.expires_in) > 0 ? Number(r.expires_in) : 300;
    token = { valor: r.access_token, caduca: Date.now() + (segundos - 60) * 1000 };
    return token.valor;
  }

  const base = `/${cfg.version}`;
  const pagos = `${base}/rechargeProviders/${encodeURIComponent(cfg.provider)}/payments`;

  return {
    // Devuelve el id numérico del usuario, o null si no existe.
    // PENDIENTE DE VERIFICAR con un servidor MyQ real: el nombre del filtro y
    // la forma de la respuesta del listado de usuarios.
    async buscarUsuario(nombre) {
      const r = await pedir('GET', `${base}/users?username=${encodeURIComponent(nombre)}`);
      const lista = Array.isArray(r) ? r : r.users || r.items || r.data || [];
      const igual = (v) => typeof v === 'string' && v.toLowerCase() === nombre.toLowerCase();
      const u = lista.find((x) => igual(x.username) || igual(x.userName) || igual(x.name));
      return u && Number.isInteger(Number(u.id)) ? Number(u.id) : null;
    },

    // Crea la recarga en estado "created": todavía no suma crédito.
    async crearPago(userId, centimos, descripcion) {
      const r = await pedir('POST', pagos, {
        cuerpo: { userId, description: descripcion, params: { amount: centimos / 100 } },
      });
      const id = Number(r.id ?? r.paymentId);
      if (!Number.isInteger(id)) throw new MyqError('MyQ no devolvió el id del pago');
      return id;
    },

    // Confirma la recarga: el crédito se suma a la cuenta del usuario.
    async confirmarPago(paymentId) {
      return pedir('POST', `${pagos}/${paymentId}/commit`, { cuerpo: {} });
    },
  };
}
