"""Celdas de 512 x 512 píxeles a 20 m (10,24 km) sobre la grilla de cada tile Sentinel-2.

Las usan `plan.py` (secciones ocupadas, para repartir el costo) y `serie_sentinel2.py --parte` (lectura): las dos
deben calcular las mismas celdas. Las celdas están alineadas al origen del tile, que es el tamaño del bloque
interno de las bandas de 10 m, de B8A y de SCL (docs/spec-chile.md, etapa satelite).
"""

from dataclasses import dataclass

import numpy as np
import shapely
from shapely import STRtree

RES = 20  # metros por píxel de la grilla de trabajo; B11 y SCL son nativas de 20 m
CELDA_PX = 512
CELDA_M = CELDA_PX * RES


@dataclass(frozen=True)
class GrillaTile:
    """Grilla de 20 m de un tile: origen (esquina superior izquierda), tamaño en píxeles y número de celdas."""

    x0: float
    y0: float
    ancho: int
    alto: int

    @property
    def ncols(self) -> int:
        return -(-self.ancho // CELDA_PX)

    @property
    def nfilas(self) -> int:
        return -(-self.alto // CELDA_PX)

    def limites(self, fila: int, col0: int, col1: int | None = None) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) de la fila de celdas `col0` a `col1` (inclusive); una sola celda si no hay col1."""
        col1 = col0 if col1 is None else col1
        xmin = self.x0 + col0 * CELDA_M
        ymax = self.y0 - fila * CELDA_M
        return (xmin, ymax - CELDA_M, self.x0 + (col1 + 1) * CELDA_M, ymax)

    def transformada(self, fila: int, col0: int):
        from rasterio.transform import Affine

        return Affine(RES, 0, self.x0 + col0 * CELDA_M, 0, -RES, self.y0 - fila * CELDA_M)


def grilla_de_item(item) -> GrillaTile:
    """Grilla del tile desde el ítem STAC (`proj:transform` y `proj:shape` de la banda roja, a 10 m)."""
    rojo = item.assets["red"].extra_fields
    t, forma = rojo["proj:transform"], rojo["proj:shape"]
    return GrillaTile(x0=t[2], y0=t[5], ancho=-(-forma[1] // 2), alto=-(-forma[0] // 2))


def celdas_ocupadas(geometrias, grilla: GrillaTile) -> list[tuple[int, int]]:
    """Celdas (fila, columna) que tocan alguna geometría (en el CRS del tile), en orden de fila y columna."""
    celdas = [(f, c) for f in range(grilla.nfilas) for c in range(grilla.ncols)]
    cajas = shapely.box(*np.array([grilla.limites(f, c) for f, c in celdas]).T)
    toca = STRtree(np.asarray(list(geometrias), dtype=object)).query(cajas, predicate="intersects")[0]
    return [celdas[i] for i in sorted(set(toca.tolist()))]


def tramos(celdas: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Agrupa celdas en tramos horizontales contiguos: (fila, col_inicio, col_fin), con col_fin inclusive."""
    salida = []
    for f, c in sorted((int(f), int(c)) for f, c in celdas):  # int de Python: rasterio no acepta np.int64 en out_shape
        if salida and salida[-1][0] == f and salida[-1][2] == c - 1:
            salida[-1] = (f, salida[-1][1], c)
        else:
            salida.append((f, c, c))
    return salida
