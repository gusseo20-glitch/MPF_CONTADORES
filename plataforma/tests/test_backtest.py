import unittest

from plataforma.backtest import MotorBacktest, calcular_metricas
from plataforma.broker import Costes, SIN_COSTES, unidades_asequibles
from plataforma.datos import ProveedorSintetico
from plataforma.estrategias import crear_estrategia
from plataforma.modelos import Barra, Operacion
from plataforma.riesgo import ParametrosRiesgo


def serie_alcista(n=400, inicio=100.0, paso=0.5):
    barras = []
    precio = inicio
    for i in range(n):
        apertura = precio
        precio += paso
        barras.append(Barra(f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                            apertura, max(apertura, precio) * 1.001,
                            min(apertura, precio) * 0.999, precio, 1000))
    return barras


class PruebasBacktest(unittest.TestCase):
    def test_sin_datos_falla(self):
        with self.assertRaises(ValueError):
            MotorBacktest(crear_estrategia("cruce_medias")).ejecutar({})

    def test_comprar_y_mantener_replica_el_activo(self):
        barras = serie_alcista(300)
        motor = MotorBacktest(crear_estrategia("comprar_y_mantener"), 1000.0, SIN_COSTES)
        resultado = motor.ejecutar({"X": barras})
        subida_activo = barras[-1].cierre / barras[1].apertura - 1
        self.assertAlmostEqual(resultado.metricas["rendimiento_total"], subida_activo, places=2)

    def test_capital_nunca_negativo(self):
        barras = ProveedorSintetico(semilla=11, volatilidad_anual=0.9).historico("X", 800)
        resultado = MotorBacktest(crear_estrategia("momentum"), 50.0,
                                  Costes()).ejecutar({"X": barras})
        self.assertTrue(all(v >= -1e-9 for _, v in resultado.curva))
        self.assertGreaterEqual(resultado.capital_final, 0.0)

    def test_los_costes_reducen_el_resultado(self):
        barras = ProveedorSintetico(semilla=5, deriva_anual=0.2).historico("X", 900)
        estrategia = "cruce_medias"
        sin = MotorBacktest(crear_estrategia(estrategia), 1000.0, SIN_COSTES).ejecutar({"X": barras})
        con = MotorBacktest(crear_estrategia(estrategia), 1000.0,
                            Costes(comision_fija=5.0, deslizamiento_pb=20)).ejecutar({"X": barras})
        if sin.metricas["operaciones"] > 0:
            self.assertLess(con.capital_final, sin.capital_final)

    def test_todas_las_posiciones_se_liquidan(self):
        barras = ProveedorSintetico(semilla=2).historico("X", 700)
        resultado = MotorBacktest(crear_estrategia("tendencia_ema"), 500.0).ejecutar({"X": barras})
        self.assertEqual(len(resultado.cartera.posiciones), 0)

    def test_stop_limita_la_perdida_por_operacion(self):
        barras = ProveedorSintetico(semilla=8, deriva_anual=-0.3,
                                    volatilidad_anual=0.5).historico("X", 900)
        riesgo = ParametrosRiesgo(riesgo_por_operacion=0.02, caida_maxima=0.99,
                                  importe_minimo=1.0)
        resultado = MotorBacktest(crear_estrategia("momentum"), 1000.0, SIN_COSTES,
                                  riesgo).ejecutar({"X": barras})
        for operacion in resultado.operaciones:
            # margen amplio por huecos de apertura, pero ninguna perdida catastrofica
            self.assertGreater(operacion.rendimiento, -0.15, operacion.a_dict())

    def test_multiples_simbolos_comparten_capital(self):
        datos = {s: ProveedorSintetico(semilla=i).historico(s, 700)
                 for i, s in enumerate("ABC")}
        resultado = MotorBacktest(crear_estrategia("cruce_medias"), 100.0).ejecutar(datos)
        self.assertLessEqual(max(v for _, v in resultado.curva), 100.0 * 20)

    def test_metricas_con_curva_vacia(self):
        m = calcular_metricas([], [], 50.0)
        self.assertEqual(m["operaciones"], 0)
        self.assertEqual(m["rendimiento_total"], 0.0)

    def test_unidades_asequibles_recorta(self):
        costes = Costes(comision_fija=1.0, deslizamiento_pb=10)
        self.assertEqual(unidades_asequibles(costes, 0, 10, 5), 0.0)
        ajustadas = unidades_asequibles(costes, 50, 10, 100)
        self.assertLess(ajustadas * 10 + 1.0, 50.1)

    def test_operacion_calcula_beneficio_neto(self):
        op = Operacion("X", "2024-01-01", "2024-02-01", 100, 110, 2, 3.0, "objetivo", 1000)
        self.assertAlmostEqual(op.beneficio, 17.0)
        self.assertAlmostEqual(op.rendimiento, 0.017)
        self.assertTrue(op.ganadora)


if __name__ == "__main__":
    unittest.main()
