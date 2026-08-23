import unittest

from plataforma import montecarlo
from plataforma.modelos import Operacion


def operaciones(rendimientos):
    return [Operacion("X", "2024-01-01", "2024-01-02", 100, 100 * (1 + r), 1, 0.0, "test", 1.0)
            for r in rendimientos]


class PruebasMonteCarlo(unittest.TestCase):
    def test_sin_operaciones_falla(self):
        with self.assertRaises(ValueError):
            montecarlo.desde_operaciones([], 50.0)

    def test_estrategia_perdedora_no_duplica(self):
        resultado = montecarlo.simular([-0.05] * 10, 50.0, horizonte=30, simulaciones=200)
        self.assertEqual(resultado.prob_objetivo, 0.0)
        self.assertEqual(resultado.prob_perdida, 1.0)

    def test_estrategia_ganadora_duplica_siempre(self):
        resultado = montecarlo.simular([0.10] * 5, 50.0, horizonte=20, simulaciones=200)
        self.assertEqual(resultado.prob_objetivo, 1.0)
        self.assertGreater(resultado.mediana, 100.0)

    def test_es_reproducible(self):
        muestra = [0.05, -0.03, 0.02, -0.01]
        a = montecarlo.simular(muestra, 50.0, horizonte=50, simulaciones=500, semilla=1)
        b = montecarlo.simular(muestra, 50.0, horizonte=50, simulaciones=500, semilla=1)
        self.assertEqual(a.mediana, b.mediana)
        self.assertEqual(a.prob_objetivo, b.prob_objetivo)

    def test_percentiles_ordenados(self):
        r = montecarlo.simular([0.03, -0.02, 0.01], 50.0, horizonte=40, simulaciones=500)
        self.assertLessEqual(r.p5, r.p25)
        self.assertLessEqual(r.p25, r.mediana)
        self.assertLessEqual(r.mediana, r.p75)
        self.assertLessEqual(r.p75, r.p95)

    def test_ruina_se_detecta(self):
        r = montecarlo.simular([-0.5], 50.0, horizonte=20, simulaciones=100)
        self.assertEqual(r.prob_ruina, 1.0)

    def test_operaciones_necesarias(self):
        self.assertEqual(montecarlo.operaciones_necesarias(0.0), float("inf"))
        self.assertAlmostEqual(montecarlo.operaciones_necesarias(1.0, 2.0), 1.0)

    def test_desde_operaciones_usa_rendimientos(self):
        r = montecarlo.desde_operaciones(operaciones([0.02, -0.01, 0.03]), 50.0,
                                         horizonte=10, simulaciones=200)
        self.assertEqual(r.metodo, "operaciones")
        self.assertEqual(r.simulaciones, 200)


if __name__ == "__main__":
    unittest.main()
