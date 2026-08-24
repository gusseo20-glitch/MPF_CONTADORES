import unittest

from plataforma.modelos import Barra, Posicion
from plataforma.riesgo import GestorRiesgo, ParametrosRiesgo


class PruebasRiesgo(unittest.TestCase):
    def setUp(self):
        self.gestor = GestorRiesgo(ParametrosRiesgo(riesgo_por_operacion=0.02,
                                                    fraccion_maxima=0.5,
                                                    importe_minimo=10.0))

    def test_tamano_respeta_riesgo_maximo(self):
        unidades = self.gestor.unidades(1000, 1000, precio=100, stop=90)
        # 2% de 1000 = 20 EUR de riesgo; 10 EUR de riesgo por unidad -> 2 unidades
        self.assertAlmostEqual(unidades, 2.0, places=6)

    def test_tamano_respeta_concentracion(self):
        unidades = self.gestor.unidades(1000, 1000, precio=100, stop=99.9)
        self.assertLessEqual(unidades * 100, 1000 * 0.5 + 1e-9)

    def test_tamano_nulo_por_debajo_del_minimo(self):
        self.assertEqual(self.gestor.unidades(50, 50, precio=100, stop=50), 0.0)

    def test_sin_efectivo_no_hay_posicion(self):
        self.assertEqual(self.gestor.unidades(1000, 0, precio=10, stop=9), 0.0)

    def test_cortacircuitos(self):
        self.assertFalse(self.gestor.revisar_cortacircuitos(100))
        self.assertFalse(self.gestor.revisar_cortacircuitos(90))
        self.assertTrue(self.gestor.revisar_cortacircuitos(70))
        self.assertFalse(self.gestor.puede_abrir(0))
        self.assertIn("caida", self.gestor.motivo_detencion)

    def test_stop_dinamico_nunca_baja(self):
        posicion = Posicion("X", 1, 100, "2024-01-01", stop=95, maximo_favorable=100)
        barras = [Barra(f"d{i}", 100, 102, 98, 100) for i in range(30)]
        self.gestor.actualizar_stop_dinamico(posicion, Barra("d30", 120, 122, 118, 120), barras)
        subido = posicion.stop
        self.assertGreaterEqual(subido, 95)
        self.gestor.actualizar_stop_dinamico(posicion, Barra("d31", 90, 91, 89, 90), barras)
        self.assertEqual(posicion.stop, subido)

    def test_salida_por_stop_tiene_prioridad(self):
        posicion = Posicion("X", 1, 100, "2024-01-01", stop=95, objetivo=110)
        hay, precio, motivo = self.gestor.salida_forzosa(
            posicion, Barra("d1", 100, 115, 90, 112))
        self.assertTrue(hay)
        self.assertEqual(motivo, "stop")
        self.assertLessEqual(precio, 95)


if __name__ == "__main__":
    unittest.main()
