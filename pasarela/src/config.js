const env = process.env;

function requerido(nombre) {
  const v = env[nombre];
  if (!v) throw new Error(`Falta la variable de entorno ${nombre}`);
  return v;
}

export function cargarConfig() {
  const version = env.REDSYS_SIGNATURE_VERSION || 'HMAC_SHA512_V2';
  if (!['HMAC_SHA512_V2', 'HMAC_SHA256_V1'].includes(version)) {
    throw new Error('REDSYS_SIGNATURE_VERSION debe ser HMAC_SHA512_V2 o HMAC_SHA256_V1');
  }
  return {
    port: Number(env.PORT || 3000),
    publicUrl: requerido('PUBLIC_URL').replace(/\/+$/, ''),
    databaseUrl: requerido('DATABASE_URL'),
    adminToken: requerido('ADMIN_TOKEN'),
    alertWebhookUrl: env.ALERT_WEBHOOK_URL || '',
    importeMin: Number(env.IMPORTE_MIN_CENTIMOS || 100),
    importeMax: Number(env.IMPORTE_MAX_CENTIMOS || 10000),
    // Un pago sin completar se da por abandonado pasado este tiempo
    caducidadMinutos: Number(env.CADUCIDAD_MINUTOS || 120),
    // Tiempo máximo reintentando la recarga antes de pedir revisión manual
    limiteReintentosHoras: Number(env.LIMITE_REINTENTOS_HORAS || 24),
    workerIntervaloMs: Number(env.WORKER_INTERVALO_MS || 30000),
    redsys: {
      url: requerido('REDSYS_URL'),
      merchantCode: requerido('REDSYS_MERCHANT_CODE'),
      terminal: env.REDSYS_TERMINAL || '1',
      key: requerido('REDSYS_KEY'),
      // Firma de las peticiones: HMAC_SHA512_V2 (actual) o HMAC_SHA256_V1 (anterior)
      signatureVersion: version,
      merchantName: env.REDSYS_MERCHANT_NAME || 'Recarga de impresión',
      currency: '978', // EUR
    },
    myq: {
      apiUrl: requerido('MYQ_API_URL').replace(/\/+$/, ''),
      version: env.MYQ_API_VERSION || 'v3',
      clientId: requerido('MYQ_CLIENT_ID'),
      clientSecret: requerido('MYQ_CLIENT_SECRET'),
      scope: env.MYQ_SCOPE || 'credit users',
      provider: env.MYQ_PROVIDER || 'external',
      timeoutMs: Number(env.MYQ_TIMEOUT_MS || 15000),
    },
  };
}
