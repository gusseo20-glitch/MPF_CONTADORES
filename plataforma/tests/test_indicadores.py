import math
import unittest

from plataforma.indicadores import (atr, ema, maxima_caida, percentil, rsi, sharpe, sma,
                                    volatilidad_anual)
from plataforma.modelos import Barra


class PruebasIndicadores(unittest.TestCase):
    def test_sma_basica(self):
        self.assertEqual(sma([1, 2, 3, 4], 2), 3.5)
        self.assertIsNone(sma([1], 5))

    def test_ema_converge_a_constante(self):
        self.assertAlmostEqual(ema([5.0] * 30, 10), 5.0, places=6)

    def test_rsi_extremos(self):
        subida = list(range(1, 40))
        self.assertAlmostEqual(rsi(subida, 14), 100.0, places=6)
        bajada = list(range(40, 1, -1))
        self.assertAlmostEqual(rsi(bajada, 14), 0.0, places=6)

    def test_rsi_sin_datos_suficientes(self):
        self.assertIsNone(rsi([1, 2, 3], 14))

    def test_atr_constante(self):
        barras = [Barra(f"d{i}", 10, 11, 9, 10) for i in range(30)]
        self.assertAlmostEqual(atr(barras, 14), 2.0, places=6)

    def test_maxima_caida(self):
        self.assertAlmostEqual(maxima_caida([100, 120, 60, 90]), 0.5, places=6)
        self.assertEqual(maxima_caida([10, 11, 12]), 0.0)

    def test_volatilidad_serie_plana(self):
        self.assertEqual(volatilidad_anual([100] * 50), 0.0)

    def test_sharpe_serie_plana(self):
        self.assertEqual(sharpe([0.0] * 30), 0.0)

    def test_percentil(self):
        self.assertEqual(percentil([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(percentil([1, 2], 50), 1.5)


if __name__ == "__main__":
    unittest.main()
