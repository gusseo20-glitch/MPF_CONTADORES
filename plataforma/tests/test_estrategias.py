import unittest

from plataforma.datos import ProveedorSintetico
from plataforma.estrategias import ESTRATEGIAS, crear_estrategia
from plataforma.modelos import Barra


def serie(precios):
    return [Barra(f"2024-01-{i + 1:02d}", p, p * 1.01, p * 0.99, p, 1000)
            for i, p in enumerate(precios)]


class PruebasEstrategias(unittest.TestCase):
    def test_nombre_desconocido(self):
        with self.assertRaises(ValueError):
            crear_estrategia("no_existe")

    def test_todas_devuelven_senal_valida(self):
        barras = ProveedorSintetico().historico("X", 600)
        for nombre in ESTRATEGIAS:
            estrategia = crear_estrategia(nombre)
            senal = estrategia.evaluar(barras, False)
            self.assertIn(senal.accion, ("COMPRAR", "VENDER", "MANTENER"), nombre)

    def test_sin_historial_no_opera(self):
        for nombre in ESTRATEGIAS:
            if nombre == "comprar_y_mantener":
                continue
            estrategia = crear_estrategia(nombre)
            self.assertEqual(estrategia.evaluar(serie([10, 11]), False).accion, "MANTENER",
                             nombre)

    def test_comprar_y_mantener_compra_una_vez(self):
        estrategia = crear_estrategia("comprar_y_mantener")
        self.assertEqual(estrategia.evaluar(serie([10]), False).accion, "COMPRAR")
        self.assertEqual(estrategia.evaluar(serie([10]), True).accion, "MANTENER")

    def test_cruce_medias_detecta_giro_alcista(self):
        precios = [100 - i for i in range(160)] + [40 + i * 2 for i in range(60)]
        estrategia = crear_estrategia("cruce_medias", rapida=5, lenta=20, filtro=0)
        acciones = set()
        en_posicion = False
        barras = serie(precios)
        for i in range(len(barras)):
            senal = estrategia.evaluar(barras[:i + 1], en_posicion)
            if senal.accion == "COMPRAR":
                en_posicion = True
            elif senal.accion == "VENDER":
                en_posicion = False
            acciones.add(senal.accion)
        self.assertIn("COMPRAR", acciones)

    def test_no_mira_al_futuro(self):
        """La senal de la barra t no puede cambiar al anadir barras posteriores."""
        barras = ProveedorSintetico(semilla=3).historico("X", 500)
        estrategia = crear_estrategia("cruce_medias")
        corte = 400
        senal_parcial = estrategia.evaluar(barras[:corte], False)
        senal_con_futuro = crear_estrategia("cruce_medias").evaluar(barras[:corte], False)
        self.assertEqual(senal_parcial.accion, senal_con_futuro.accion)


if __name__ == "__main__":
    unittest.main()
