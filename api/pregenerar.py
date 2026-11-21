"""Genera los expedientes de la demo (candidato y predio del caso de data/demo.json) con los datos de la imagen.

Se corre al construir la imagen de caudal-api (api/Dockerfile): así el expediente del candidato ya existe, con la
misma huella de insumos que calcula la API, y el botón de la ficha lo abre al instante. La respuesta de la API lo
marca `reutilizado` y muestra su fecha de creación. Sin red, salen sin imágenes (`con_imagenes: false`).

Uso: python -m api.pregenerar
"""

from . import datos, expedientes


def main() -> None:
    d = datos.demo()
    predios = [d["candidato"], next(c["predio_id"] for c in datos.casos()["casos"] if c["expediente"] == d["caso"])]
    for pid in predios:
        e = expedientes.solicitar(int(pid))
        print(f"{e['id']}: predio {pid}, temporada {e['temporada']}, {'con' if e['con_imagenes'] else 'sin'} imágenes, "
              f"{'ya existía' if e['reutilizado'] else str(e['segundos']) + ' s'}")


if __name__ == "__main__":
    main()
