import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from plataforma.api import crear_servidor
from plataforma.bot import Bot
from plataforma.config import Config


def config_prueba(estado: str, **extra) -> Config:
    base = dict(capital=50.0, simbolos=["A", "B"], proveedor="sintetico",
                estrategia="comprar_y_mantener", dias=400, estado=estado,
                costes={"comision_fija": 0.0, "comision_porcentual": 0.0005,
                        "comision_minima": 0.0, "deslizamiento_pb": 5.0,
                        "tasa_operaciones": 0.0})
    base.update(extra)
    return Config(**base)


class PruebasBot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.estado = os.path.join(self.tmp, "estado.json")

    def test_ciclo_abre_posicion_y_persiste(self):
        bot = Bot(config_prueba("estado.json"), ruta_estado=self.estado)
        bot.reiniciar()
        resultado = bot.ejecutar_ciclo()
        self.assertTrue(os.path.exists(self.estado))
        self.assertIn(resultado["posiciones"], (1, 2))
        recargado = Bot(config_prueba("estado.json"), ruta_estado=self.estado)
        self.assertEqual(len(recargado.cartera.posiciones), len(bot.cartera.posiciones))
        self.assertAlmostEqual(recargado.cartera.efectivo, bot.cartera.efectivo, places=6)

    def test_no_gasta_mas_del_capital(self):
        bot = Bot(config_prueba("estado.json"), ruta_estado=self.estado)
        bot.reiniciar()
        for _ in range(3):
            bot.ejecutar_ciclo()
        self.assertGreaterEqual(bot.cartera.efectivo, -1e-9)

    def test_modo_desconocido_no_arranca(self):
        with self.assertRaises(RuntimeError):
            Bot(config_prueba("estado.json", modo="real"), ruta_estado=self.estado)

    def test_reiniciar_vuelve_al_capital_inicial(self):
        bot = Bot(config_prueba("estado.json"), ruta_estado=self.estado)
        bot.ejecutar_ciclo()
        bot.reiniciar()
        self.assertEqual(bot.cartera.efectivo, 50.0)
        self.assertEqual(bot.cartera.posiciones, {})


class PruebasApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.servidor = crear_servidor(config_prueba(os.path.join(cls.tmp, "estado.json")), 0)
        cls.puerto = cls.servidor.server_address[1]
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def url(self, ruta):
        return f"http://127.0.0.1:{self.puerto}{ruta}"

    def get(self, ruta):
        with urllib.request.urlopen(self.url(ruta), timeout=60) as r:
            return json.load(r)

    def post(self, ruta, cuerpo):
        peticion = urllib.request.Request(
            self.url(ruta), data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(peticion, timeout=120) as r:
            return json.load(r)

    def test_sirve_el_panel(self):
        with urllib.request.urlopen(self.url("/"), timeout=30) as r:
            self.assertIn("Plataforma", r.read().decode("utf-8"))

    def test_lista_estrategias(self):
        datos = self.get("/api/estrategias")
        self.assertIn("cruce_medias", [e["nombre"] for e in datos["estrategias"]])

    def test_backtest_por_api(self):
        datos = self.post("/api/backtest", {"simbolos": "A", "estrategia": "momentum",
                                            "capital": 50, "dias": 500,
                                            "proveedor": "sintetico"})
        self.assertIn("metricas", datos)
        self.assertIn("referencia", datos)
        self.assertGreater(len(datos["curva"]), 100)

    def test_estrategia_invalida_da_400(self):
        try:
            self.post("/api/backtest", {"estrategia": "trampa", "proveedor": "sintetico"})
            self.fail("deberia haber fallado")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)

    def test_no_permite_salir_de_la_carpeta_web(self):
        try:
            with urllib.request.urlopen(self.url("/../plataforma/api.py"), timeout=30):
                self.fail("no deberia servir ficheros fuera de web/")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)


if __name__ == "__main__":
    unittest.main()
