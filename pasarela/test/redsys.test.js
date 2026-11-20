import test from 'node:test';
import assert from 'node:assert/strict';
import { crearFormulario, verificarNotificacion, estaAutorizado, firmar } from '../src/redsys.js';
import { aCentimos } from '../src/orders.js';

const key = 'sq7HjrUOBfKmC576ILgskD5srU870gJ7'; // clave pública del entorno de pruebas de Redsys
const cfg = { key, url: 'https://tpv/pago', merchantCode: '999008881', terminal: '1', currency: '978', merchantName: 'Test' };

// Firmas de referencia obtenidas con una implementación independiente (redsys-easy 6.0.1)
test('firma idéntica a la implementación de referencia', () => {
  const pedido = '000000000042';
  assert.equal(firmar('HMAC_SHA256_V1', key, pedido, REF.datos + '=='), REF.sha256);
  assert.equal(firmar('HMAC_SHA512_V2', key, pedido, REF.datos), REF.sha512);
});

function notificacion(params, version = 'HMAC_SHA512_V2') {
  const datos = Buffer.from(JSON.stringify(params)).toString('base64');
  return { Ds_SignatureVersion: version, Ds_MerchantParameters: datos, Ds_Signature: firmar(version, key, params.Ds_Order, datos) };
}

test('el formulario lleva importe, pedido y firma verificable', () => {
  for (const signatureVersion of ['HMAC_SHA512_V2', 'HMAC_SHA256_V1']) {
    const f = crearFormulario({ ...cfg, signatureVersion }, { numeroPedido: '000000000007', centimos: 1234, urlNotificacion: 'n', urlOk: 'o', urlKo: 'k' });
    const p = JSON.parse(Buffer.from(f.campos.Ds_MerchantParameters, 'base64').toString());
    assert.equal(p.DS_MERCHANT_AMOUNT, '1234');
    assert.equal(p.DS_MERCHANT_ORDER, '000000000007');
    assert.equal(f.campos.Ds_SignatureVersion, signatureVersion);
    assert.equal(f.campos.Ds_Signature, firmar(signatureVersion, key, '000000000007', f.campos.Ds_MerchantParameters));
  }
});

test('acepta notificaciones bien firmadas en las tres versiones', () => {
  for (const v of ['HMAC_SHA512_V2', 'HMAC_SHA512_V1', 'HMAC_SHA256_V1']) {
    const n = notificacion({ Ds_Order: '000000000007', Ds_Amount: '1234' }, v);
    assert.equal(verificarNotificacion(cfg, n).Ds_Amount, '1234');
    // también con la firma en la otra variante de base64
    const otra = n.Ds_Signature.includes('-') || n.Ds_Signature.includes('_')
      ? n.Ds_Signature.replace(/-/g, '+').replace(/_/g, '/')
      : n.Ds_Signature.replace(/\+/g, '-').replace(/\//g, '_');
    assert.equal(verificarNotificacion(cfg, { ...n, Ds_Signature: otra }).Ds_Amount, '1234');
  }
});

test('rechaza firma falsa, datos alterados, otra clave y versión desconocida', () => {
  const n = notificacion({ Ds_Order: '000000000007', Ds_Amount: '1234', Ds_Response: '0000' });
  const alterados = Buffer.from(JSON.stringify({ Ds_Order: '000000000007', Ds_Amount: '1', Ds_Response: '0000' })).toString('base64');
  assert.throws(() => verificarNotificacion(cfg, { ...n, Ds_MerchantParameters: alterados }), /Firma/);
  assert.throws(() => verificarNotificacion(cfg, { ...n, Ds_Signature: 'AAAA' }), /Firma/);
  assert.throws(() => verificarNotificacion({ ...cfg, key: 'Mk9m98IfEblmPfrpsawt7BmxObt98Jev' }, n), /Firma/);
  assert.throws(() => verificarNotificacion(cfg, { ...n, Ds_SignatureVersion: 'NINGUNA' }), /admitida/);
  assert.throws(() => verificarNotificacion(cfg, { ...n, Ds_SignatureVersion: undefined }), /admitida/);
  assert.throws(() => verificarNotificacion(cfg, {}), /incompleta/);
  assert.throws(() => verificarNotificacion(cfg, { ...n, Ds_Signature: ['a', 'b'] }), /incompleta/);
});

test('solo los códigos 0000-0099 son pago autorizado', () => {
  for (const r of ['0000', '0', '0099', '99']) assert.equal(estaAutorizado({ Ds_Response: r }), true, r);
  for (const r of ['0100', '0190', '9915', '', undefined, '-1', '00a', ' 0']) assert.equal(estaAutorizado({ Ds_Response: r }), false, String(r));
});

test('conversión de importes a céntimos', () => {
  assert.equal(aCentimos('10'), 1000);
  assert.equal(aCentimos('10,5'), 1050);
  assert.equal(aCentimos('10.50'), 1050);
  assert.equal(aCentimos(' 0,05 '), 5);
  assert.equal(aCentimos('19.99'), 1999);
  for (const malo of ['', 'abc', '-5', '1.234', '1e3', '10,', '1,2,3', null]) assert.equal(aCentimos(malo), null, String(malo));
});

const REF = {
  datos: 'eyJEU19NRVJDSEFOVF9BTU9VTlQiOiIxMDUwIiwiRFNfTUVSQ0hBTlRfT1JERVIiOiIwMDAwMDAwMDAwNDIifQ',
  sha256: 'Z2rqRrv0ZY0uTa4u13i49qizxh4uBjhcZJ03wYqY6Vo=',
  sha512: 'QJd5PJOv-7GtqxwPk8drmZapvbEVCiN4YBkqv-GIQGwCYClJ4cOd-qBqjGe1rZIoMehA0gSOQXqSS4vpETmfEw',
};
