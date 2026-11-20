// Firma y verificación del TPV virtual Redsys (integración por redirección).
// Admite la firma actual HMAC_SHA512_V2 y la anterior HMAC_SHA256_V1.
import crypto from 'node:crypto';

export const VERSIONES = ['HMAC_SHA512_V2', 'HMAC_SHA512_V1', 'HMAC_SHA256_V1'];

// SHA-256: la clave del pedido es el 3DES-CBC (IV a ceros, relleno con ceros)
// del número de pedido con la clave del comercio.
function firmarSha256(claveB64, pedido, datos) {
  const clave = Buffer.from(claveB64, 'base64');
  if (clave.length !== 24) throw new Error('REDSYS_KEY no es una clave válida (24 bytes en base64)');
  const texto = Buffer.from(pedido, 'utf8');
  const relleno = Buffer.alloc(Math.ceil(texto.length / 8) * 8);
  texto.copy(relleno);
  const cifrador = crypto.createCipheriv('des-ede3-cbc', clave, Buffer.alloc(8));
  cifrador.setAutoPadding(false);
  const clavePedido = Buffer.concat([cifrador.update(relleno), cifrador.final()]);
  return crypto.createHmac('sha256', clavePedido).update(datos).digest('base64');
}

// SHA-512: la clave del pedido es el AES-128-CBC del número de pedido, usando
// como clave los 16 primeros caracteres de la clave del comercio (como texto).
// La clave del HMAC es ese resultado en base64 (la cadena, no sus bytes).
function firmarSha512(claveB64, pedido, datos) {
  const clave = Buffer.from(claveB64.slice(0, 16).padEnd(16, '0'), 'utf8');
  const cifrador = crypto.createCipheriv('aes-128-cbc', clave, Buffer.alloc(16));
  const clavePedido = Buffer.concat([cifrador.update(pedido, 'utf8'), cifrador.final()]).toString('base64');
  return crypto.createHmac('sha512', clavePedido).update(datos).digest('base64url');
}

export function firmar(version, claveB64, pedido, datos) {
  if (version === 'HMAC_SHA256_V1') return firmarSha256(claveB64, pedido, datos);
  if (version === 'HMAC_SHA512_V2' || version === 'HMAC_SHA512_V1') return firmarSha512(claveB64, pedido, datos);
  throw new Error(`Versión de firma no admitida: ${version}`);
}

// Campos del formulario que el navegador del usuario envía a Redsys.
export function crearFormulario(cfg, { numeroPedido, centimos, urlNotificacion, urlOk, urlKo }) {
  const parametros = {
    DS_MERCHANT_AMOUNT: String(centimos),
    DS_MERCHANT_ORDER: numeroPedido,
    DS_MERCHANT_MERCHANTCODE: cfg.merchantCode,
    DS_MERCHANT_CURRENCY: cfg.currency,
    DS_MERCHANT_TRANSACTIONTYPE: '0',
    DS_MERCHANT_TERMINAL: cfg.terminal,
    DS_MERCHANT_MERCHANTURL: urlNotificacion,
    DS_MERCHANT_URLOK: urlOk,
    DS_MERCHANT_URLKO: urlKo,
    DS_MERCHANT_MERCHANTNAME: cfg.merchantName,
    DS_MERCHANT_PRODUCTDESCRIPTION: 'Recarga de credito de impresion',
  };
  const version = cfg.signatureVersion || 'HMAC_SHA512_V2';
  // HMAC_SHA512_V2 exige los parámetros en base64url sin relleno
  const codificacion = version === 'HMAC_SHA512_V2' ? 'base64url' : 'base64';
  const datos = Buffer.from(JSON.stringify(parametros), 'utf8').toString(codificacion);
  return {
    url: cfg.url,
    campos: {
      Ds_SignatureVersion: version,
      Ds_MerchantParameters: datos,
      Ds_Signature: firmar(version, cfg.key, numeroPedido, datos),
    },
  };
}

// Valida una notificación de Redsys. Devuelve los parámetros decodificados
// solo si la firma es correcta; en caso contrario lanza un error.
export function verificarNotificacion(cfg, cuerpo) {
  const { Ds_SignatureVersion, Ds_MerchantParameters, Ds_Signature } = cuerpo || {};
  if (typeof Ds_MerchantParameters !== 'string' || typeof Ds_Signature !== 'string' || !Ds_MerchantParameters || !Ds_Signature) {
    throw new Error('Notificación incompleta');
  }
  if (!VERSIONES.includes(Ds_SignatureVersion)) {
    throw new Error(`Versión de firma no admitida: ${Ds_SignatureVersion}`);
  }
  let parametros;
  try {
    parametros = JSON.parse(Buffer.from(Ds_MerchantParameters, 'base64').toString('utf8'));
  } catch {
    throw new Error('Ds_MerchantParameters ilegible');
  }
  const pedido = parametros?.Ds_Order;
  if (typeof pedido !== 'string' || !pedido) throw new Error('Notificación sin número de pedido');

  // Se comparan los bytes: Redsys puede enviar base64 o base64url, con o sin relleno
  const esperada = Buffer.from(firmar(Ds_SignatureVersion, cfg.key, pedido, Ds_MerchantParameters), 'base64');
  const recibida = Buffer.from(Ds_Signature, 'base64');
  if (esperada.length !== recibida.length || !crypto.timingSafeEqual(esperada, recibida)) {
    throw new Error('Firma de Redsys no válida');
  }
  return parametros;
}

// Redsys autoriza el pago cuando el código de respuesta está entre 0000 y 0099.
export function estaAutorizado(parametros) {
  const r = String(parametros.Ds_Response ?? '');
  return /^\d{1,4}$/.test(r) && Number(r) <= 99;
}
