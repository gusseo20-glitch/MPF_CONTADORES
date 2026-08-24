import json
import os
import tempfile
import unittest
from unittest import mock

from plataforma.alpaca import BrokerAlpaca, ClienteAlpaca, ErrorAlpaca
from plataforma.bot import Bot
from plataforma.config import Config

CREDENCIALES = {"APCA_API_KEY_ID": "clave-prueba", "APCA_API_SECRET_KEY": "secreto-prueba"}


class TransporteFalso:
    """Simula la API de Alpaca: rellena toda orden al precio indicado."""

    def __init__(self, precio=100.0, rechazar_duplicados=False):
        self.precio = precio
        self.rechazar_duplicados = rechazar_duplicados
        self.ordenes = {}
        self.por_id_cliente = {}
        self.peticiones = []
        self.contador = 0

    def __call__(self, metodo, ruta, cuerpo=None):
        self.peticiones.append((metodo, ruta, cuerpo))
        if metodo == "POST" and ruta == "/v2/orders":
            idc = cuerpo.get("client_order_id")
            if self.rechazar_duplicados and idc in self.por_id_cliente:
                return 422, {"message": "client_order_id must be unique"}
            self.contador += 1
            if "notional" in cuerpo:
                qty = float(cuerpo["notional"]) / self.precio
            else:
                qty = float(cuerpo["qty"])
            orden = {"id": f"orden-{self.contador}", "status": "filled",
                     "symbol": cuerpo["symbol"], "side": cuerpo["side"],
                     "filled_qty": f"{qty:.9f}", "filled_avg_price": f"{self.precio}"}
            self.ordenes[orden["id"]] = orden
            if idc:
                self.por_id_cliente[idc] = orden
            return 200, orden
        if metodo == "GET" and ruta.startswith("/v2/orders:by_client_order_id"):
            idc = ruta.split("client_order_id=")[1]
            return 200, self.por_id_cliente[idc.replace("%3A", ":")]
        if metodo == "GET" and ruta.startswith("/v2/orders/"):
            return 200, self.ordenes[ruta.rsplit("/", 1)[1]]
        if metodo == "GET" and ruta == "/v2/account":
            return 200, {"status": "ACTIVE", "cash": "48.50", "equity": "50.25"}
        if metodo == "GET" and ruta == "/v2/positions":
            return 200, [{"symbol": "SPY", "qty": "0.05", "avg_entry_price": "500.0",
                          "current_price": "505.0", "unrealized_pl": "0.25"}]
        if metodo == "GET" and ruta == "/v2/clock":
            return 200, {"is_open": False, "next_open": "2026-08-24T13:30:00Z"}
        return 404, {"message": f"ruta no simulada: {metodo} {ruta}"}


def cliente_falso(transporte=None, papel=True):
    with mock.patch.dict(os.environ, CREDENCIALES):
        return ClienteAlpaca(papel=papel, transporte=transporte or TransporteFalso())


class PruebasCliente(unittest.TestCase):
    def test_sin_credenciales_falla(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ErrorAlpaca):
                ClienteAlpaca()

    def test_papel_y_real_usan_urls_distintas(self):
        self.assertIn("paper", cliente_falso(papel=True).base)
        self.assertNotIn("paper", cliente_falso(papel=False).base)

    def test_error_http_se_traduce(self):
        cliente = cliente_falso()
        with self.assertRaises(ErrorAlpaca):
            cliente._pedir("GET", "/v2/no-existe")

    def test_orden_duplicada_recupera_la_original(self):
        transporte = TransporteFalso(rechazar_duplicados=True)
        cliente = cliente_falso(transporte)
        primera = cliente.orden_mercado("SPY", "buy", notional=25.0, id_cliente="dup-1")
        segunda = cliente.orden_mercado("SPY", "buy", notional=25.0, id_cliente="dup-1")
        self.assertEqual(primera["id"], segunda["id"])
        envios = [p for p in transporte.peticiones if p[0] == "POST"]
        self.assertEqual(len(envios), 2)  # el segundo POST fue rechazado por el broker


class PruebasBrokerAlpaca(unittest.TestCase):
    def test_compra_usa_notional_y_devuelve_relleno_real(self):
        transporte = TransporteFalso(precio=200.0)
        broker = BrokerAlpaca(cliente_falso(transporte))
        ejecucion = broker.comprar("QQQ", unidades=0.1, precio=199.0, fecha="2026-08-24")
        envio = [p for p in transporte.peticiones if p[0] == "POST"][0][2]
        self.assertIn("notional", envio)
        self.assertAlmostEqual(float(envio["notional"]), 19.90)
        self.assertEqual(ejecucion.precio, 200.0)          # precio real, no el estimado
        self.assertEqual(ejecucion.comision, 0.0)

    def test_venta_usa_cantidad(self):
        transporte = TransporteFalso(precio=150.0)
        broker = BrokerAlpaca(cliente_falso(transporte))
        broker.vender("AAPL", unidades=0.25, precio=149.0, fecha="2026-08-24")
        envio = [p for p in transporte.peticiones if p[0] == "POST"][0][2]
        self.assertEqual(envio["side"], "sell")
        self.assertEqual(float(envio["qty"]), 0.25)

    def test_es_irreversible(self):
        self.assertTrue(BrokerAlpaca.irreversible)


class PruebasBotConAlpaca(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.estado = os.path.join(self.tmp, "estado.json")

    def _bot(self, modo="papel"):
        config = Config(capital=50.0, simbolos=["A", "B"], proveedor="sintetico",
                        estrategia="comprar_y_mantener", dias=400, modo=modo)
        return Bot(config, ruta_estado=self.estado)

    def test_modo_real_exige_confirmacion(self):
        with mock.patch.dict(os.environ, CREDENCIALES):
            os.environ.pop("PLATAFORMA_DINERO_REAL", None)
            with self.assertRaises(RuntimeError):
                self._bot("alpaca_real")

    def test_modo_real_con_confirmacion_arranca(self):
        entorno = dict(CREDENCIALES, PLATAFORMA_DINERO_REAL="acepto")
        with mock.patch.dict(os.environ, entorno):
            bot = self._bot("alpaca_real")
        self.assertEqual(bot.broker.nombre, "alpaca")
        self.assertFalse(bot.broker.cliente.papel)

    def test_alpaca_papel_no_necesita_confirmacion(self):
        with mock.patch.dict(os.environ, CREDENCIALES):
            bot = self._bot("alpaca_papel")
        self.assertTrue(bot.broker.cliente.papel)

    def test_ciclo_completo_contra_broker_simulado(self):
        transporte = TransporteFalso(precio=100.0)
        bot = self._bot("papel")
        bot.broker = BrokerAlpaca(cliente_falso(transporte))
        bot.reiniciar()
        resultado = bot.ejecutar_ciclo()
        compras = [a for a in resultado["acciones"] if a["tipo"] == "compra"]
        self.assertGreaterEqual(len(compras), 1)
        for posicion in bot.cartera.posiciones.values():
            self.assertEqual(posicion.precio_entrada, 100.0)  # precio del broker
        self.assertGreaterEqual(bot.cartera.efectivo, -0.01)

    def test_sincronizar_trae_cartera_del_broker(self):
        bot = self._bot("papel")
        bot.broker = BrokerAlpaca(cliente_falso())
        resultado = bot.sincronizar()
        self.assertEqual(bot.cartera.efectivo, 48.50)
        self.assertIn("SPY", bot.cartera.posiciones)
        posicion = bot.cartera.posiciones["SPY"]
        self.assertEqual(posicion.unidades, 0.05)
        self.assertIsNotNone(posicion.stop)
        self.assertEqual(len(resultado["posiciones"]), 1)

    def test_sincronizar_sin_alpaca_falla_claro(self):
        bot = self._bot("papel")
        with self.assertRaises(RuntimeError):
            bot.sincronizar()


if __name__ == "__main__":
    unittest.main()
