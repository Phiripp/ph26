# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow", "truststore"]
# ///
"""Prueba D20-A: ¿se pueden bajar los datos del Monitoreo de Extracciones Efectivas (MEE) de la DGA?

El MEE es el sistema donde cada titular informa caudal, totalizador y nivel freático por obra de captación.
Esta prueba llama a todo lo público que se encontró y anota qué responde. No usa login, ni captcha, ni credenciales.

Qué se probó:
1. Software MEE (https://snia.mop.gob.cl/cExtracciones2/): es una aplicación Angular. Sus servicios
   (/extracciones/data/...) responden 403 sin el token que la propia página pide a /mee-auth-rest/v1/authorization
   con una clave embebida en su JavaScript. Esa clave no se usa aquí: es una credencial de la aplicación.
   Además, la búsqueda pública de obras (busquedaPublica/obtenerObrasResumen) y la descarga de reportes por región,
   naturaleza y mes (reporte/getList y reporte/downloadReporteMEE, un CSV) exigen un reCAPTCHA resuelto.
2. API de transmisión (https://apimee.mop.gob.cl, OpenAPI público en /api-docs): es para que los titulares envíen
   mediciones. Leer exige el número de comprobante de un envío o el RUT y la clave del informante.
3. datos.gob.cl y los ArcGIS de MOP (rest-sit.mop.gob.cl) y SMA (ideserver.sma.gob.cl): sin capas ni conjuntos MEE.
4. ArcGIS Online de la DGA (usuario DGA_SITMinisterial, services3.arcgis.com/aSoEm9TBK2shtWjP): lo único que responde.
   - Cobertura MEE subterráneas (marzo 2026) y superficiales (julio 2025): polígonos con la resolución, los rangos
     de caudal de cada estándar y el plazo. Se consultan por bbox. Dicen quién debe informar, no cuánto extrae.
   - "Monitoreo Extracciones Efectivas": revisión de mayo de 2024, solo provincia de Limarí (Coquimbo). Trae
     código de obra, UTM, estándar y mediciones exigidas y realizadas; los meses son el caudal autorizado, no el
     medido. Tiene RUT, nombres y correos: aquí solo se piden estadísticas y campos sin datos personales.

Con la cobertura y data/processed/derecho.parquet se cuenta cuántos derechos subterráneos de Z1 y Z2 caen en cada
estándar MEE (los que deberían estar informando). No es un conteo de obras registradas: eso no se puede contar.

Uso: uv run scripts/pruebas_datos/04_mee_dga.py
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import truststore

# Los sitios de mop.gob.cl envían una cadena que el bundle de Python no valida; el almacén del sistema sí.
truststore.inject_into_ssl()

RAIZ = Path(__file__).resolve().parents[2]
ZONAS = RAIZ / "data" / "zonas.json"
DERECHO = RAIZ / "data" / "processed" / "derecho.parquet"
UA = {"User-Agent": "Mozilla/5.0 (prueba-acceso-datos/0.1)"}

SNIA = "https://snia.mop.gob.cl"
APIMEE = "https://apimee.mop.gob.cl"
AGOL = "https://services3.arcgis.com/aSoEm9TBK2shtWjP/arcgis/rest/services"
COB_SUB = f"{AGOL}/Cobertura_MEE_Aguas_Subterraneas_2026/FeatureServer/0"
COB_SUP = f"{AGOL}/Cobertura_del_Monitoreo_de_Extracciones_Efectivas_de_Aguas_Superficiales/FeatureServer/0"
REVISION = f"{AGOL}/Monitoreo_Extracciones_Efectivas/FeatureServer"

SIN_TOKEN = {"paginator": None, "token": None, "userName": None}
# Territorio de la cobertura subterránea que contiene las comunas de cada zona (todas de una misma provincia).
TERRITORIO_ZONA = {"Z1": "Petorca", "Z2": "Quillota"}
EXPEDIENTE = r"[A-Z]{2,3}-\d{4}-\d+"


def pedir(url: str, cuerpo: dict | None = None, params: dict | None = None) -> tuple[int | str, float, bytes]:
    """Estado HTTP (o el error), segundos y cuerpo. Con `cuerpo` es un POST JSON."""
    if params:
        url += "?" + urllib.parse.urlencode(params)
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cab = UA | ({"Content-Type": "application/json"} if datos else {})
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=datos, headers=cab), timeout=60) as r:
            return r.status, time.time() - t, r.read()
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t, e.read()
    except Exception as e:  # red caída, DNS, certificado
        return type(e).__name__, time.time() - t, b""


def linea(nombre: str, estado, seg: float, nota: str = "") -> None:
    print(f"{nombre}: {estado} en {seg:.1f} s{'  ' + nota if nota else ''}")


def texto(cuerpo: bytes, n: int = 90) -> str:
    return re.sub(r"\s+", " ", cuerpo.decode("utf-8", "replace"))[:n]


def consulta(capa: str, **params) -> tuple[int | str, float, list[dict]]:
    estado, seg, cuerpo = pedir(f"{capa}/query", params={"f": "json", "returnGeometry": "false", **params})
    filas = [f["attributes"] for f in json.loads(cuerpo).get("features", [])] if estado == 200 else []
    return estado, seg, filas


def conteo(capa: str, campo: str) -> tuple[int | str, float, dict]:
    stats = json.dumps([{"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"}])
    estado, seg, filas = consulta(capa, where="1=1", groupByFieldsForStatistics=campo, outStatistics=stats)
    return estado, seg, {f[campo]: f["n"] for f in filas}


def probar_software_mee() -> None:
    print("== 1. Software MEE (snia.mop.gob.cl), sin token ni captcha")
    estado, seg, cuerpo = pedir(f"{SNIA}/cExtracciones2/")
    linea("GET /cExtracciones2/", estado, seg, f"{len(cuerpo)} B, solo la carcasa de la aplicación")
    for ruta, datos in (
        ("/extracciones/data/busquedaPublica/obtenerObrasResumen", {"region": {"codigo": 5}}),
        ("/extracciones/data/reporte/getList", {"region": {"codigo": 5}, "naturaleza": 1, "periodo": "01-2026"}),
        ("/extracciones/data/parametroSelector/getRegiones", None),
    ):
        estado, seg, cuerpo = pedir(SNIA + ruta, {"metaData": SIN_TOKEN, "data": datos})
        linea(f"POST {ruta}", estado, seg, texto(cuerpo, 60))


def probar_api_transmision() -> None:
    print("\n== 2. API de transmisión (apimee.mop.gob.cl), sin credenciales")
    estado, seg, cuerpo = pedir(f"{APIMEE}/api-docs")
    linea("GET /api-docs", estado, seg)
    if estado == 200:
        doc = json.loads(cuerpo)
        for ruta, metodos in doc["paths"].items():
            for metodo, d in metodos.items():
                params = [p["name"] for p in d.get("parameters", [])]
                pide = (d.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema", {})
                print(f"  {metodo.upper()} {ruta}  parámetros {params}  cuerpo {pide.get('$ref', '-').rsplit('/', 1)[-1]}")
        print("  Autenticacion =", list(doc["components"]["schemas"]["Autenticacion"]["properties"]))
    for ruta in ("/api/v1/mediciones/subterraneas", "/api/v1/mediciones/subterraneas?codigoObra=OB-0501-1",
                 "/api/v1/mediciones/ultimas-mediciones?codigoObra=OB-0501-1"):
        estado, seg, cuerpo = pedir(APIMEE + ruta)
        linea(f"GET {ruta}", estado, seg, texto(cuerpo))


def probar_catalogos() -> None:
    print("\n== 3. Catálogos")
    for q in ("extracciones efectivas", "MEE", "monitoreo extracciones"):
        estado, seg, cuerpo = pedir("https://datos.gob.cl/api/3/action/package_search", params={"q": q})
        n = json.loads(cuerpo)["result"]["count"] if estado == 200 else "-"
        linea(f"datos.gob.cl q='{q}'", estado, seg, f"{n} conjuntos")
    for nombre, url in (("MOP rest-sit, carpeta DGA", "https://rest-sit.mop.gob.cl/arcgis/rest/services/DGA"),
                        ("SMA ideserver, carpeta IDE", "https://ideserver.sma.gob.cl/arcgis/rest/services/IDE")):
        estado, seg, cuerpo = pedir(url, params={"f": "json"})
        servicios = [s["name"] for s in json.loads(cuerpo).get("services", [])] if estado == 200 else []
        mee = [s for s in servicios if re.search(r"mee|extracc|captaci", s, re.I)]
        linea(nombre, estado, seg, f"{len(servicios)} servicios, con MEE o extracciones: {mee or 'ninguno'}")
    estado, seg, cuerpo = pedir("https://www.arcgis.com/sharing/rest/search",
                                params={"q": "Monitoreo Extracciones Efectivas", "f": "json", "num": 20})
    linea("ArcGIS Online, búsqueda", estado, seg)
    if estado == 200:
        for r in json.loads(cuerpo)["results"]:
            if r["type"] == "Feature Service":
                print(f"  {r['title']} ({r['owner']})  {r['url']}")


def cobertura(zonas: dict) -> dict:
    print("\n== 4. Cobertura MEE por bbox (ArcGIS Online de la DGA)")
    rangos = {}
    for z, d in zonas.items():
        for nombre, capa in (("subterráneas", COB_SUB), ("superficiales", COB_SUP)):
            estado, seg, filas = consulta(capa, where="1=1", outFields="*", geometry=",".join(map(str, d["bbox"])),
                                          geometryType="esriGeometryEnvelope", inSR=4326,
                                          spatialRel="esriSpatialRelIntersects")
            linea(f"{z} {nombre}", estado, seg, f"{len(filas)} territorios tocan el bbox")
            for f in filas:
                g = lambda *claves: next((f[k] for k in claves if f.get(k)), "")  # noqa: E731
                print(f"  {g('TERRITORIO').strip()[:60]} ({g('TIPO_TERRITORIO')}), res. "
                      f"{g('NUM_RES_DGA', 'NUMERO_RESOLUCIÓN')} del {g('FECHA_RES', 'FECHA_RESOLUCIÓN')}, plazo "
                      f"{g('PLAZO_STATUS')}: mayor {g('RANGO_ESTANDAR_MAYOR', 'CONSUNTIVO_RANGO_ESTANDAR_MAYOR')} l/s "
                      f"desde {g('PLAZO_ESTANDAR_MAYOR')}; muy pequeños "
                      f"{g('RANGO_ESTANDAR_CAUDALES_MUY_PEQUEÑOS', 'CONSUNTIVO_RANGO_ESTANDAR_CAUDA')} l/s desde "
                      f"{g('PLAZO_ESTANDAR_CAUDALES_MUY_PEQUEÑOS', 'PLAZO_ESTANDAR_CAUDALES_MUY_PEQ')}")
                if nombre == "subterráneas" and g("TERRITORIO") == TERRITORIO_ZONA.get(z):
                    rangos[z] = f
    return rangos


def numero(s: str) -> float:
    return float(re.search(r"\d+(?:,\d+)?", s).group().replace(",", "."))


def derechos_por_estandar(rangos: dict) -> None:
    print("\n== 5. Derechos subterráneos de derecho.parquet por estándar MEE (universo que debería informar)")
    d = pd.read_parquet(DERECHO, columns=["zona", "expediente", "naturaleza", "caudal_ls", "sumable"])
    calza = d["expediente"].str.fullmatch(EXPEDIENTE).mean()
    print(f"Expedientes con el formato de la DGA (ND-0501-123), el mismo que usa el MEE: {calza:.1%} de {len(d)}")
    sub = d[(d["naturaleza"] == "subterranea") & d["sumable"]]
    for z, f in rangos.items():
        mayor, medio, menor = (numero(f[f"RANGO_ESTANDAR_{k}"]) for k in ("MAYOR", "MEDIO", "MENOR"))
        q = sub.loc[sub["zona"] == z, "caudal_ls"]
        # Rangos de la resolución: muy pequeños <= menor; menor (menor, medio]; medio (medio, mayor); mayor >= mayor.
        estandar = pd.Series("muy pequeños", index=q.index).mask(q > menor, "menor").mask(q > medio, "medio")
        estandar = estandar.mask(q >= mayor, "mayor")
        orden = ["mayor", "medio", "menor", "muy pequeños"]
        n = estandar.value_counts().reindex(orden, fill_value=0)
        ls = q.groupby(estandar).sum().reindex(orden, fill_value=0)
        print(f"{z} ({f['TERRITORIO']}; cortes {menor}, {medio} y {mayor} l/s): {len(q)} derechos subterráneos sumables")
        for k in n.index:
            print(f"  {k}: {n[k]} derechos, {ls[k]:,.0f} l/s ({ls[k] / q.sum():.0%} del caudal)")


def revision_limari() -> None:
    print("\n== 6. Revisión MEE de Limarí, mayo de 2024 (única capa con obras; no cubre Z1 ni Z2)")
    for capa in range(1, 5):
        estado, seg, regiones = conteo(f"{REVISION}/{capa}", "Region")
        _, _, categorias = conteo(f"{REVISION}/{capa}", "Categoria")
        linea(f"capa {capa}", estado, seg, f"obras por región {regiones}; por categoría {categorias}")
    estado, seg, categorias = conteo(f"{REVISION}/0", "Categoria_Revision")
    linea("capa 0 (derechos subterráneos revisados)", estado, seg, str(categorias))
    campos = "Codigo_Obra,Comuna,UTM_Norte,UTM_Este,Huso,Estandar,Caudal_medio_Anual_l_s,Certificado_N_Año_Expediente," \
             "N_de_mediciones_exigidas,N_de_mediciones_realizadas"
    con_expediente = total = 0
    for capa in range(1, 5):
        _, _, filas = consulta(f"{REVISION}/{capa}", where="1=1", outFields=campos)
        total += len(filas)
        con_expediente += sum(bool(re.search(EXPEDIENTE, f["Certificado_N_Año_Expediente"] or "")) for f in filas)
        if capa == 1:
            for f in filas[:3]:
                print("  ", f)
    print(f"Obras con un código de expediente legible en Certificado_N_Año_Expediente: {con_expediente} de {total}")


def main() -> None:
    zonas = json.loads(ZONAS.read_text(encoding="utf-8"))["zonas"]
    probar_software_mee()
    probar_api_transmision()
    probar_catalogos()
    rangos = cobertura(zonas)
    derechos_por_estandar(rangos)
    revision_limari()


if __name__ == "__main__":
    main()
