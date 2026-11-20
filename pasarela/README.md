# Pasarela de recarga MyQ X + Redsys

Servicio que permite a un usuario de MyQ X recargar su crédito de impresión
pagando con tarjeta en el TPV virtual de Redsys.

## Cómo funciona

1. El usuario indica su usuario de MyQ y el importe.
2. El servicio guarda el pedido y crea en MyQ una recarga **pendiente** (todavía no suma crédito).
   Si MyQ no responde, no se envía al usuario a pagar.
3. El usuario paga en la página de Redsys. Los datos de tarjeta nunca pasan por este servicio.
4. Redsys avisa al servicio con una notificación firmada (`POST /redsys/notificacion`).
   Se comprueba la firma, el código de respuesta y que importe, moneda, comercio y terminal coinciden.
5. El servicio confirma la recarga en MyQ y el crédito queda disponible.

### Estados de un pedido

| Estado | Significado |
|---|---|
| `creado` | Guardado, sin recarga pendiente en MyQ todavía |
| `pendiente_pago` | Enviado a Redsys, esperando la notificación |
| `pagado` | Cobrado; falta confirmar en MyQ (se reintenta solo) |
| `recargado` | Cobrado y crédito sumado. Estado final correcto |
| `denegado` | El banco no autorizó el pago |
| `caducado` | El usuario no completó el pago |
| `fallido` | No se pudo preparar la recarga. No se cobró nada |
| `revision_manual` | Cobrado y sin recargar tras agotar reintentos. Lo resuelve soporte |

### Garantías

- **Una recarga por pedido.** Las notificaciones repetidas o simultáneas no suman crédito dos veces.
- **Solo acredita la notificación firmada de Redsys.** La página a la que vuelve el usuario solo muestra el estado.
- **Reintentos automáticos** si MyQ falla tras el cobro: 30 s, 1 min, 2 min… hasta 30 min entre intentos, durante 24 h.
- **Alertas** ante firma inválida, datos que no coinciden, MyQ caído o pedido que pasa a revisión manual.
- **Registro de eventos** por pedido en la tabla `eventos`.

## Puesta en marcha

Requisitos: Node.js 20.6 o superior y PostgreSQL 13 o superior.

```bash
cd pasarela
npm install
cp .env.example .env      # y rellenar los valores
npm run migrate           # crea las tablas (también se aplica al arrancar)
npm start
```

El servicio debe publicarse por **HTTPS** en la dirección indicada en `PUBLIC_URL`, y debe poder
conectar con el servidor MyQ. Si MyQ usa un certificado propio, indica su CA con la variable de
Node `NODE_EXTRA_CA_CERTS`.

### Configuración en MyQ X

1. Activar el crédito y el proveedor **External Payment Providers** en Configuración → Crédito.
2. Registrar una aplicación para la API REST con los permisos (scopes) de crédito y de usuarios,
   y copiar su identificador y secreto a `MYQ_CLIENT_ID` y `MYQ_CLIENT_SECRET`.
3. La moneda del servidor MyQ debe ser el euro.

### Configuración en Redsys

- `REDSYS_MERCHANT_CODE`, `REDSYS_TERMINAL` y `REDSYS_KEY` los facilita el banco.
- En el panel del TPV, activar la **notificación online HTTP**. La URL se envía en cada pago.
- Para pruebas se usa `https://sis-t.redsys.es:25443/sis/realizarPago` con las credenciales de test del banco.

## Soporte

Todas las rutas de `/admin` requieren la cabecera `Authorization: Bearer <ADMIN_TOKEN>`.

| Ruta | Uso |
|---|---|
| `GET /admin/pedidos?estado=&usuario=&pedido=` | Lista los últimos 200 pedidos, con filtros opcionales |
| `GET /admin/pedidos/:id/eventos` | Historial completo de un pedido |
| `POST /admin/pedidos/:id/reintentar` | Relanza la recarga de un pedido en `revision_manual` |
| `GET /salud` | Comprobación de disponibilidad (sin token) |

## Pruebas

```bash
TEST_DATABASE_URL=postgres://usuario@localhost:5432/pasarela_test npm test
```

Las pruebas de flujo borran y recrean las tablas de esa base de datos: usa una dedicada a pruebas.
Sin `TEST_DATABASE_URL` solo se ejecutan las pruebas de firma.

## Pendiente antes de producción

- **Verificar contra un servidor MyQ real.** El cliente de MyQ está escrito a partir de la documentación
  pública y solo se ha probado con un MyQ simulado. Hay que comprobar en particular:
  - la búsqueda de usuario por nombre (`GET /v3/users?username=`), cuyo filtro y formato de respuesta no están confirmados;
  - que confirmar dos veces el mismo pago no suma crédito dos veces;
  - los nombres exactos de los scopes.
- **Probar contra el entorno de pruebas de Redsys.** La firma coincide con una implementación
  independiente, pero no se ha hecho ningún pago real de prueba.
- **Consulta de estado a Redsys.** Si una notificación no llega nunca, el pedido caduca aunque
  esté cobrado. Falta consultar a Redsys los pedidos sin notificación antes de caducarlos.
- **Devolución automática.** Un pedido en `revision_manual` se devuelve hoy a mano desde el panel de Redsys.
- **Identificación del usuario.** Cualquiera puede recargar la cuenta de cualquier usuario escribiendo su nombre.
- **Límite de peticiones** en el formulario público, y alertas por correo (hoy van al log y a un webhook).
