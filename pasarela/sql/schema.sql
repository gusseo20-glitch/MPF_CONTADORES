CREATE SEQUENCE IF NOT EXISTS pedidos_numero_seq;

CREATE TABLE IF NOT EXISTS pedidos (
  id                  BIGSERIAL PRIMARY KEY,
  -- Número de pedido Redsys: 12 dígitos, único por comercio/terminal
  numero_pedido       TEXT NOT NULL UNIQUE
                      DEFAULT lpad(nextval('pedidos_numero_seq')::text, 12, '0'),
  -- Identificador no adivinable para la página de resultado del usuario
  token               UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  usuario_myq         TEXT NOT NULL,
  myq_user_id         BIGINT,
  myq_payment_id      BIGINT,
  importe_centimos    INTEGER NOT NULL CHECK (importe_centimos > 0),
  estado              TEXT NOT NULL CHECK (estado IN (
                        'creado',           -- guardado, aún sin recarga pendiente en MyQ
                        'pendiente_pago',   -- enviado a Redsys, esperando notificación
                        'pagado',           -- cobrado; falta confirmar la recarga en MyQ
                        'recargado',        -- cobrado y crédito sumado en MyQ (final)
                        'denegado',         -- Redsys denegó el pago
                        'caducado',         -- el usuario no completó el pago
                        'fallido',          -- no se pudo preparar (no se cobró nada)
                        'revision_manual'   -- cobrado y sin recargar tras agotar reintentos
                      )),
  redsys_respuesta    TEXT,
  redsys_autorizacion TEXT,
  intentos            INTEGER NOT NULL DEFAULT 0,
  proximo_intento     TIMESTAMPTZ,
  ultimo_error        TEXT,
  creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
  pagado_en           TIMESTAMPTZ,
  recargado_en        TIMESTAMPTZ,
  actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pedidos_pendientes_idx
  ON pedidos (proximo_intento) WHERE estado = 'pagado';
CREATE INDEX IF NOT EXISTS pedidos_estado_idx ON pedidos (estado, creado_en);

-- Registro de todo lo que le ocurre a cada pedido (auditoría y reclamaciones)
CREATE TABLE IF NOT EXISTS eventos (
  id         BIGSERIAL PRIMARY KEY,
  pedido_id  BIGINT REFERENCES pedidos(id),
  tipo       TEXT NOT NULL,
  detalle    JSONB,
  creado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS eventos_pedido_idx ON eventos (pedido_id);
