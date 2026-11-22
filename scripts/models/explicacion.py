# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "shapely>=2.0", "scikit-learn"]
# ///
"""Explicación de una alerta: por qué un predio está (o no) en alerta, con fuentes y límites (tarea T1 de spec-demo).

Responde tres preguntas, en este orden y nada más (docs/spec-demo.md, "Por qué este predio está en alerta"):
1. Qué vimos: hasta 4 razones (riego sin lluvia, consumo, derechos, contexto). Cada una es una frase con su número,
   su fuente y un enlace a la referencia.
2. Qué tan seguros estamos: la confianza de M5 y sus motivos, en una frase cada uno.
3. Qué no sabemos: hasta 2 límites, iguales para todo predio.

Todo sale de las filas de M3 y M5; aquí no se calcula ningún número nuevo, solo se redactan. La misma función
(`explicacion`) la usan la ficha de la API (api/datos.py) y el expediente PDF (expediente.py), para que digan lo mismo.
Los m³ van en rango y redondeados (función `m3`). La primera vista no usa términos técnicos (NDVI, z, percentil):
los valores crudos van en `valor`, para "ver método".

Entradas de `explicacion`:
- m5: fila de puntaje.parquet o puntaje_validacion.parquet (M5) del predio y la temporada.
- senal: fila de senal_riego*.parquet (M3) del predio y la temporada (n_fechas_senal). Opcional.
- fechas: filas por imagen de la temporada, marcadas con detector_riego.marcar_senal (fecha, escena_id, valida,
  senal, ref_ndvi_mediana). Opcional: dan la lista de escenas, el período y el verdor del secano.
- contexto: {"fiscalizado_500m": bool, "corte_derechos": fecha} (opcional).

`explicar(predio_id, temporada)` carga esas filas desde data/processed/ (para la línea de comandos y las pruebas).

Uso:
  uv run scripts/models/explicacion.py --predio-id 5301984
  uv run scripts/models/explicacion.py --predio-id 5301413 --temporada 2020-21      # caso FO-0504-95, antes de la inspección
"""

import argparse
import json
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PROC = RAIZ / "data" / "processed"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from detector_riego import DIAS_MIN, FRAC_MIN, UMBRAL_HUMEDAD, UMBRAL_VERDOR  # noqa: E402

MAX_RAZONES, MAX_LIMITES = 4, 2
ANO_FISCALIZACIONES = 2018  # impacto.sin_fiscalizar_500m cuenta las fiscalizaciones desde este año
METODO = "data/README.md#índice-de-sospecha-m5"  # ancla de GitHub
VALIDACION = "docs/validacion.md"

FUENTES = {
    "riego_sin_lluvia": {
        "fuente": "Imágenes Sentinel-2 (Copernicus); lluvia de DMC y Open-Meteo",
        "referencia": "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a",
        "metodo": "scripts/models/detector_riego.py"},
    "consumo": {
        "fuente": "Método FAO-56 (FAO, 1998), con eficiencia de riego de 75 % a 90 %",
        "referencia": "https://www.fao.org/4/x0490s/x0490s00.htm",
        "metodo": "scripts/models/consumo_fao56.py"},
    "derechos": {
        "fuente": "Registro de derechos de aprovechamiento de aguas de la DGA",
        "referencia": "https://dga.mop.gob.cl/derechos-de-agua/derechos-registrados/",
        "metodo": "scripts/models/indice_sospecha.py"},
    "contexto": {
        "fuente": "Canales de la CNR y CIREN (2020); planilla de fiscalización de la DGA",
        "referencia": "https://dga.mop.gob.cl/tramites/denunciar/fiscalizacion/",
        "metodo": "scripts/extract/canales_ciren.py"},
}

# Motivos de confianza de M3 y M5 (columna `motivos`), en una frase.
TEXTO_MOTIVO = {
    "sin_derechos_propios_ubicados": "No encontramos derechos ubicados en el predio; podría tener derechos sin coordenada en el registro",
    "derechos_ajenos_cubren_exceso": "Hay derechos de vecinos a 500 m que podrían cubrir el consumo",
    "canal_300m": "Hay un canal a menos de 300 m: puede regar con acciones de canal, que no están en el registro",
    "predio_grande": "Predio de más de 100 ha: la señal se diluye",
    "pocos_pixeles": "Predio chico: pocas mediciones por imagen",
    "cruce_derechos_media": "La ubicación del derecho en el registro es incierta",
    "cruce_derechos_baja": "La ubicación del derecho en el registro es incierta",
    "pocas_fechas": "Pocas imágenes útiles en la temporada",
    "nubosidad": "Muchas imágenes con nubes",
    "sin_clima": "Sin dato de lluvia para parte de la temporada",
    "sin_referencia": "Sin cerro seco de referencia cerca",
    "referencia_provisional": "El cerro de referencia es provisional",
    "temporada_incompleta_m4": "El consumo se estimó con la temporada incompleta",
    "clima_climatologia": "Parte del clima se completó con promedios históricos",
    "sin_consumo_m4": "Sin estimación de consumo para esta temporada",
}

LIMITES = [
    "Caudal ve que se riega, no de dónde sale el agua. La infracción la constata un inspector.",
    "El consumo es una estimación en rango, no una medición.",
]


def _nulo(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x)) or x != x


def entero(x) -> str:
    """Entero con punto de miles."""
    return f"{round(float(x)):,}".replace(",", ".")


def m3(x) -> str:
    """m³ a 2 cifras significativas, o 3 si la primera es 1 (104.648 -> 105.000, no 100.000): un rango no merece más
    precisión. Es el redondeo de la ficha y del expediente."""
    if _nulo(x):
        return "s/d"
    x = float(x)
    if x == 0:
        return "0"
    e = int(math.floor(math.log10(abs(x))))
    p = 10 ** max(e - (2 if abs(x) / 10 ** e < 2 else 1), 0)
    return entero(round(x / p) * p)


def distancia(metros) -> str:
    m = float(metros)
    return f"{entero(m)} m" if m < 1000 else f"{m / 1000:.1f} km".replace(".", ",")


def _fecha(x) -> str:
    return str(x)[:10]


def lista_motivos(motivos) -> list[str]:
    return [m for m in str(motivos or "").split(";") if m.strip()] if not _nulo(motivos) else []


def confianza_motivos(motivos) -> list[str]:
    """Texto de cada motivo, sin repetir (los dos niveles del cruce de derechos dicen lo mismo)."""
    out = []
    for m in lista_motivos(motivos):
        t = TEXTO_MOTIVO.get(m.partition("(")[0], m.replace("_", " "))
        if t not in out:
            out.append(t)
    return out


def _riego(m5, senal, fechas) -> dict:
    n = int(m5["n_fechas_validas"]) if not _nulo(m5.get("n_fechas_validas")) else 0
    if senal is not None and not _nulo(senal.get("n_fechas_senal")):
        k = int(senal["n_fechas_senal"])
    else:
        k = round(float(m5["frac_senal"]) * n) if not _nulo(m5.get("frac_senal")) else 0
    validas = [f for f in (fechas or []) if f.get("valida")]
    secano = sorted(float(f["ref_ndvi_mediana"]) for f in validas if not _nulo(f.get("ref_ndvi_mediana")))
    valor = {"fechas_con_senal": k, "fechas_validas": n, "dias_sin_lluvia_min": DIAS_MIN, "fraccion_min": FRAC_MIN,
             "umbral_verdor": UMBRAL_VERDOR, "umbral_humedad": UMBRAL_HUMEDAD,
             "verdor_predio": None if _nulo(m5.get("ndvi_mediana")) else round(float(m5["ndvi_mediana"]), 2),
             "verdor_secano": round(secano[len(secano) // 2], 2) if secano else None,
             "desde": _fecha(validas[0]["fecha"]) if validas else None,
             "hasta": _fecha(validas[-1]["fecha"]) if validas else None}
    if n == 0:
        texto = "No hay imágenes útiles tras períodos sin lluvia en la temporada: no se puede evaluar el riego."
    elif bool(m5.get("senal_riego")):
        texto = (f"Más verde y más húmedo que el cerro seco vecino en {k} de {n} imágenes tomadas tras {DIAS_MIN} días "
                 f"o más sin lluvia.")
    else:
        texto = (f"Más verde y más húmedo que el cerro seco vecino en {k} de {n} imágenes sin lluvia: no alcanza para "
                 f"una señal de riego (se piden {round(FRAC_MIN * 10)} de cada 10).")
    return {"id": "riego_sin_lluvia", "titulo": "Riego sin lluvia", "texto": texto, "valor": valor,
            "dato_al": valor["hasta"], **FUENTES["riego_sin_lluvia"]}


def _consumo(m5) -> dict:
    lo, hi = m5.get("m3_consumo_bruto_min"), m5.get("m3_consumo_bruto_max")
    if _nulo(lo) or _nulo(hi):
        texto, valor = "Sin estimación de consumo de agua para esta temporada.", None
    else:
        texto = f"Para regar esa vegetación necesita entre {m3(lo)} y {m3(hi)} m³ de agua al año."
        valor = {"m3_ano_min": round(float(lo)), "m3_ano_max": round(float(hi))}
    return {"id": "consumo", "titulo": "Consumo", "texto": texto, "valor": valor, **FUENTES["consumo"]}


def _derechos(m5, contexto) -> dict:
    propio, ajeno = m5.get("m3_derecho_asignado"), m5.get("m3_derecho_ajeno_disponible_500m")
    ex_lo, ex_hi = m5.get("m3_exceso_min"), m5.get("m3_exceso_max")
    propio = 0.0 if _nulo(propio) else float(propio)
    ajeno = 0.0 if _nulo(ajeno) else float(ajeno)
    texto = f"Derechos de agua inscritos en el predio: {m3(propio)} m³ al año. De vecinos a 500 m: {m3(ajeno)} m³."
    if not _nulo(ex_hi) and float(ex_hi) > 0:
        texto += (f" Quedan entre {m3(max(float(ex_lo), 0))} y {m3(ex_hi)} m³ al año sin un derecho que los respalde."
                  if not _nulo(ex_lo) else "")
    elif not _nulo(ex_hi):
        texto += " Los derechos cubren el consumo estimado."
    corte = contexto.get("corte_derechos")
    return {"id": "derechos", "titulo": "Derechos", "texto": texto,
            "valor": {"m3_ano_predio": round(propio), "m3_ano_vecinos_500m": round(ajeno),
                      "m3_ano_sin_respaldo_min": None if _nulo(ex_lo) else round(max(float(ex_lo), 0)),
                      "m3_ano_sin_respaldo_max": None if _nulo(ex_hi) else round(float(ex_hi))},
            "dato_al": None if _nulo(corte) else _fecha(corte), **FUENTES["derechos"]}


def _contexto(m5, contexto) -> dict:
    d = m5.get("dist_canal_m")
    partes = ["Sin canal registrado cerca." if _nulo(d) else "Un canal cruza o bordea el predio." if float(d) < 1 else
              f"Canal más cercano: a {distancia(d)}."]
    fisc = contexto.get("fiscalizado_500m")
    if fisc is not None:
        partes.append(f"La DGA fiscalizó a 500 m o menos desde {ANO_FISCALIZACIONES}." if fisc else
                      f"Sin fiscalización de la DGA a 500 m desde {ANO_FISCALIZACIONES}.")
    return {"id": "contexto", "titulo": "Contexto", "texto": " ".join(partes),
            "valor": {"dist_canal_m": None if _nulo(d) else round(float(d)),
                      "fiscalizado_500m": None if fisc is None else bool(fisc)},
            **FUENTES["contexto"]}


def explicacion(m5, senal=None, fechas=None, contexto=None, calculado=None, version_modelo=None) -> dict:
    """Contrato de la explicación (docs/spec-demo.md). Las filas pueden ser dict o pandas.Series."""
    m5 = dict(m5)
    senal = None if senal is None else dict(senal)
    contexto = contexto or {}
    fechas = sorted((dict(f) for f in (fechas or [])), key=lambda f: _fecha(f["fecha"]))
    razones = [_riego(m5, senal, fechas), _consumo(m5), _derechos(m5, contexto), _contexto(m5, contexto)]
    return {
        "predio_id": int(m5["predio_id"]), "temporada": m5["temporada"], "banda": m5["banda"],
        "confianza": m5["confianza"],
        "razones": razones[:MAX_RAZONES],
        "confianza_motivos": confianza_motivos(m5.get("motivos")),
        "limites": LIMITES[:MAX_LIMITES],
        "escenas": [{"fecha": _fecha(f["fecha"]), "escena_id": f.get("escena_id"), "senal": bool(f.get("senal"))}
                    for f in fechas if f.get("valida")],
        "metodo": METODO, "validacion": VALIDACION,
        "calculado": calculado, "version_modelo": version_modelo,
    }


def explicar(predio_id: int, temporada: str | None = None) -> dict:
    """Carga las filas del predio desde data/processed/ y arma la explicación. Sin temporada: 2025-26 si es elegible,
    o la última de la validación."""
    import pandas as pd

    from detector_riego import en_ventana, marcar_senal
    from impacto import sin_fiscalizar_500m

    def filas(nombre):
        d = pd.read_parquet(PROC / f"{nombre}.parquet", filters=[("predio_id", "==", predio_id)])
        return d if temporada is None else d[d.temporada == temporada]

    for fam, puntaje in (("_elegibles_2025-26", "puntaje"), ("_validacion", "puntaje_validacion")):
        p = filas(puntaje)
        if len(p):
            m5 = p.sort_values("temporada").iloc[-1]
            break
    else:
        raise LookupError(f"El predio {predio_id} no tiene puntaje de M5" + (f" en {temporada}" if temporada else ""))
    t = m5.temporada
    s = pd.read_parquet(PROC / f"senal_riego{fam}.parquet", filters=[("predio_id", "==", predio_id)])
    s = s[s.temporada == t]
    a = pd.read_parquet(PROC / f"anomalias_predio{fam}.parquet", filters=[("predio_id", "==", predio_id)])
    a = marcar_senal(en_ventana(a[a.temporada == t]))
    d = pd.read_parquet(PROC / "predio_derecho.parquet", columns=["predio_id", "temporada", "corte"],
                        filters=[("predio_id", "==", predio_id)])
    d = d[d.temporada == t]
    ctx = {"corte_derechos": d.corte.iloc[0] if len(d) else None}
    if (PROC / "predio.parquet").exists():
        ctx["fiscalizado_500m"] = not bool(sin_fiscalizar_500m(pd.Series([predio_id])).iloc[0])
    return explicacion(m5, s.iloc[0] if len(s) else None, a.to_dict("records"), ctx)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--predio-id", type=int, required=True)
    ap.add_argument("--temporada")
    args = ap.parse_args()
    print(json.dumps(explicar(args.predio_id, args.temporada), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
