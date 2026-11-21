# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "shapely>=2.0"]
# ///
"""Índice de sospecha por predio y temporada: banda, puntaje y confianza (tarea M5).

La sospecha sale de la señal satelital (M3); los derechos dimensionan el exceso. Los derechos solos no distinguen
infractores (AUC 0,49–0,54 entre fiscalizados) y el 73 % de los positivos tiene derechos: por eso se mide el
consumo sobre los derechos, no "tiene o no tiene derechos".

Entradas (data/processed/):
- senal_riego*.parquet (M3, --senal): senal_riego, frac_senal, confianza y motivos por predio y temporada.
- consumo_predio*_temporada.parquet (M4, --consumo): m3_anual_min/central/max (consumo neto de riego).
- predio_derecho.parquet (D5): derechos del rol en la temporada, área del rol, canal, estado y confianza del cruce.
- derecho.parquet, derecho_predio.parquet (D4, D5) y predio.parquet (D3, local): para los derechos ajenos con
  excedente a 500 m o menos.
- fiscalizacion.parquet (D6): si el predio está en el vecindario de una fiscalización por extracción de aguas.

Salida: data/processed/puntaje.parquet (o --salida), una fila por (predio_id, temporada), ordenada por rank_zona.

Cálculo:
1. Consumo bruto = consumo neto de M4 / eficiencia de aplicación, en rango: mínimo con 0,90 (goteo bien
   operado), central con 0,85 y máximo con 0,75. El consumo anual de M4 ya viene extrapolado desde la temporada.
   En predios de más de 100 ha el central es el mínimo (M4 cuenta ahí el matorral del cerro como consumo).
2. Derecho asignado al polígono = m3_anual_derecho_rol de la temporada x area_ha / area_rol_ha (un rol con varios
   polígonos reparte sus derechos por superficie). Son derechos otorgados antes del 1 de diciembre de la temporada.
3. Exceso = max(0, consumo bruto - derecho asignado), en mínimo, central y máximo.
   frac_sin_derecho = exceso central / consumo bruto central.
4. Derechos ajenos disponibles a 500 m: suma de los derechos con punto a 500 m o menos del predio, inscritos en
   otro rol, por la fracción que ese rol no usa: max(0, derecho del rol - consumo bruto central del rol) / derecho
   del rol. Un derecho sin predio asignado (pozo compartido, sin predio a 500 m) cuenta entero. Lo disponible de
   cada derecho se reparte en partes iguales entre los predios elegibles de otro rol a 500 m o menos de su punto
   (un pozo no riega entero a cada vecino). Los polígonos sin
   estimación de M4 (no elegibles, o fuera de la corrida) cuentan con consumo 0: es el supuesto conservador (un
   lote de pozo de 0,3 ha no riega nada y su derecho puede regar al vecino). Excluye grandes derechos (≥ 100 l/s)
   y los no sumables (duplicados VPC, caudal negativo), como D5, y los usos que no son riego (agua potable,
   industrial, minero, hidroeléctrico, observación; el uso vacío se cuenta).
5. Banda:
   - alta: señal de riego (M3) y exceso mínimo > 0 (aun con el consumo más bajo, falta derecho).
   - media: señal y exceso central > 0.
   - baja: señal y exceso máximo > 0.
   - sin_alerta: sin señal, o el consumo máximo cabe en los derechos.
   Con confianza baja (paso 6) la banda baja un nivel: la banda alta exige confianza media o alta.
6. Confianza: la peor de
   - la de M3 (fechas válidas, píxeles, referencia, predio de más de 100 ha);
   - la del cruce de derechos (D5) si el predio tiene derechos propios: ubicación del punto de captación;
   - media si no tiene derechos propios (puede haber derechos sin coordenada a nombre del dueño: 1.143 en la región);
   - baja si los derechos ajenos disponibles a 500 m cubren el exceso central ("derechos_ajenos_cubren_exceso");
   - media si M4 no tiene la temporada completa o usó climatología.
   canal_300m no baja la confianza (68 % de los elegibles); queda como motivo ("canal_300m") porque el agua de
   canal (acciones) no aparece en los derechos. M9 lo usa para el rango de candidatos.
7. Puntaje 0–100 para ordenar y para el premio de la ruta (M8): base de la banda (alta 75, media 50, baja 25,
   sin_alerta 0) + 25 x frac_senal x peso de la confianza (alta 1, media 0,7, baja 0,4) x percentil del exceso
   central en la zona y temporada. Todo predio alto queda sobre todo predio medio; dentro de la banda sube con la
   señal, la confianza y el volumen en juego.

Privacidad: la salida no tiene nombres. En la demo los candidatos se muestran agregados; una fiscalización "en
trámite" no es una infracción (solo se marca fiscalizado_dga, sin resultado).

Uso:
  uv run scripts/models/indice_sospecha.py                                    # elegibles 2025-26 -> puntaje.parquet
  uv run scripts/models/indice_sospecha.py --senal data/processed/senal_riego_validacion.parquet \\
      --consumo data/processed/consumo_predio_validacion_temporada.parquet --salida data/processed/puntaje_validacion.parquet
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
PROC = RAIZ / "data" / "processed"
CRS_METROS = "EPSG:32719"
NIVELES = ["baja", "media", "alta"]
EFICIENCIA = {"min": 0.90, "central": 0.85, "max": 0.75}
RADIO_M = 500
USOS_NO_RIEGO = {"Bebida/Uso Domestico/Saneamiento", "Uso Industrial", "Uso Minero", "Energia Hidroeléctrica",
                 "Para Observacion y Analisis"}
BASE_BANDA = {"alta": 75.0, "media": 50.0, "baja": 25.0, "sin_alerta": 0.0}
ORDEN_BANDA = {"alta": 0, "media": 1, "baja": 2, "sin_alerta": 3}
PESO_CONFIANZA = {"alta": 1.0, "media": 0.7, "baja": 0.4}


def ruta(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else RAIZ / q


def peor(*niveles: pd.Series) -> pd.Series:
    idx = pd.concat([n.map(NIVELES.index) for n in niveles], axis=1).min(axis=1)
    return idx.map(dict(enumerate(NIVELES)))


def bajar_a(conf: pd.Series, nivel: str, mask: pd.Series) -> pd.Series:
    """Baja la confianza a `nivel` donde mask es True (si ya era más baja, queda igual)."""
    out = conf.copy()
    out[mask] = peor(conf[mask], pd.Series(nivel, index=conf[mask].index))
    return out


def derechos_ajenos(base: pd.DataFrame, pd_t: pd.DataFrame, consumo_bruto: pd.Series, corte: pd.Timestamp,
                    predios: gpd.GeoDataFrame, derechos: gpd.GeoDataFrame, asignacion: pd.DataFrame) -> pd.Series:
    """m3 anuales de derechos de otros roles a <= RADIO_M del predio que su rol no necesita (ver docstring, paso 4)."""
    rol_de = pd_t.set_index("predio_id")["rol_id"]
    necesidad_rol = consumo_bruto.groupby(rol_de.reindex(consumo_bruto.index)).sum()
    derecho_rol = pd_t.drop_duplicates("rol_id").set_index("rol_id")["m3_anual_derecho_rol"]
    libre = ((derecho_rol - necesidad_rol.reindex(derecho_rol.index).fillna(0)).clip(lower=0)
             / derecho_rol.where(derecho_rol > 0))

    vig = derechos["fecha_resolucion"].isna() | (derechos["fecha_resolucion"] < corte)
    d = derechos[vig].merge(asignacion, on="derecho_id", how="left")
    d["rol_id"] = d["predio_id"].map(rol_de)
    d["disponible"] = np.where(d["rol_id"].notna(), d["m3_anual"] * d["rol_id"].map(libre).fillna(0), d["m3_anual"])
    d = gpd.GeoDataFrame(d[["derecho_id", "rol_id", "disponible", "geometry"]], crs=CRS_METROS)
    d = d[d["disponible"] > 0]

    # Predios elegibles de otro rol a <= RADIO_M de cada derecho: el excedente se reparte en partes iguales entre
    # ellos (un mismo pozo no puede regar entero a cada vecino).
    obj = predios[predios["elegible"]][["predio_id", "geometry"]].copy()
    obj["geometry"] = obj.buffer(RADIO_M)
    obj["rol_obj"] = obj["predio_id"].map(rol_de)
    j = gpd.sjoin(d, obj, how="inner", predicate="within")
    j = j[j["rol_id"].isna() | (j["rol_id"] != j["rol_obj"])]
    j["parte"] = j["disponible"] / j.groupby("derecho_id")["predio_id"].transform("size")
    return j[j["predio_id"].isin(base["predio_id"])].groupby("predio_id")["parte"].sum()


def fiscalizados() -> pd.Series:
    f = pd.read_parquet(PROC / "fiscalizacion.parquet", columns=["extraccion", "vecindario", "predio_id"])
    f = f[f["extraccion"].fillna(False).astype(bool)]
    ids = {int(x) for v in f["vecindario"] for x in (v if v is not None else [])}
    ids |= {int(x) for x in f["predio_id"].dropna()}
    return pd.Series(sorted(ids), dtype="int64")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--senal", default="data/processed/senal_riego_elegibles_2025-26.parquet")
    ap.add_argument("--consumo", default="data/processed/consumo_predio_elegibles_2025-26_temporada.parquet")
    ap.add_argument("--salida", default="data/processed/puntaje.parquet")
    args = ap.parse_args()
    if not (PROC / "predio.parquet").exists():
        sys.exit("Falta data/processed/predio.parquet: corre antes scripts/extract/predios_ciren.py")

    senal = pd.read_parquet(ruta(args.senal))
    consumo = pd.read_parquet(ruta(args.consumo))
    pder = pd.read_parquet(PROC / "predio_derecho.parquet")
    predios = gpd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "elegible", "geometry"]).to_crs(CRS_METROS)
    derechos = gpd.read_parquet(PROC / "derecho.parquet").to_crs(CRS_METROS)
    derechos = derechos[derechos["sumable"] & ~derechos["gran_derecho"] & ~derechos["uso"].isin(USOS_NO_RIEGO)
                        & derechos.geometry.notna() & ~derechos.geometry.is_empty]
    asignacion = pd.read_parquet(PROC / "derecho_predio.parquet", columns=["derecho_id", "predio_id"])
    asignacion = asignacion.dropna(subset=["predio_id"]).astype({"predio_id": "int64"})
    fisc = set(fiscalizados())

    cols_s = ["predio_id", "zona", "temporada", "senal_riego", "frac_senal", "n_fechas_validas", "z_verdor_mediana",
              "z_humedad_mediana", "ndvi_mediana", "ndmi_mediana", "area_ha", "confianza", "motivos_confianza"]
    cols_c = ["predio_id", "temporada", "especie_principal", "frac_fruticola", "predio_grande", "temporada_completa",
              "clima_climatologia", "m3_anual_min", "m3_anual_central", "m3_anual_max"]
    cols_d = ["predio_id", "temporada", "corte", "comuna", "rol_id", "area_rol_ha", "m3_anual_derecho_rol",
              "m3_anual_derecho_entorno_500m", "pozo_compartido_500m", "dist_canal_m", "canal_300m",
              "estado_derechos", "confianza_cruce"]
    salidas = []
    for temporada, s in senal[cols_s].groupby("temporada"):
        pd_t = pder[pder["temporada"] == temporada]
        if pd_t.empty:
            print(f"Aviso: predio_derecho no tiene la temporada {temporada}; se omite", file=sys.stderr)
            continue
        b = (s.rename(columns={"confianza": "confianza_m3", "motivos_confianza": "motivos_m3"})
             .merge(consumo[cols_c], on=["predio_id", "temporada"], how="left")
             .merge(pd_t[cols_d], on=["predio_id", "temporada"], how="left"))
        sin_consumo = b["m3_anual_central"].isna()

        for k, ef in EFICIENCIA.items():
            b[f"m3_consumo_bruto_{k}"] = (b[f"m3_anual_{k}"] / ef).round(0)
        # Predios de más de 100 ha: el central de M4 cuenta el matorral del cerro como consumo; se usa el mínimo.
        grande = b["predio_grande"].fillna(False).astype(bool)
        b.loc[grande, "m3_consumo_bruto_central"] = b.loc[grande, "m3_consumo_bruto_min"]
        b["m3_derecho_asignado"] = (b["m3_anual_derecho_rol"].fillna(0)
                                    * (b["area_ha"] / b["area_rol_ha"]).clip(upper=1).fillna(1)).round(0)
        for k in EFICIENCIA:
            b[f"m3_exceso_{k}"] = (b[f"m3_consumo_bruto_{k}"] - b["m3_derecho_asignado"]).clip(lower=0)
        b["frac_sin_derecho"] = (b["m3_exceso_central"] / b["m3_consumo_bruto_central"]).where(
            b["m3_consumo_bruto_central"] > 0, 0.0).round(3)

        # Consumo bruto de todos los polígonos con M4 en la temporada (no solo los de la señal).
        c_t = consumo[consumo["temporada"] == temporada].set_index("predio_id")["m3_anual_central"]
        ajenos = derechos_ajenos(b, pd_t, c_t / EFICIENCIA["central"], pd_t["corte"].iloc[0],
                                 predios, derechos, asignacion)
        b["m3_derecho_ajeno_disponible_500m"] = b["predio_id"].map(ajenos).fillna(0.0).round(0)

        senal_ok = b["senal_riego"].fillna(False).astype(bool)
        b["banda"] = "sin_alerta"
        b.loc[senal_ok & (b["m3_exceso_max"] > 0), "banda"] = "baja"
        b.loc[senal_ok & (b["m3_exceso_central"] > 0), "banda"] = "media"
        b.loc[senal_ok & (b["m3_exceso_min"] > 0), "banda"] = "alta"

        # Confianza.
        motivos = {i: [m] if isinstance(m, str) and m else [] for i, m in b["motivos_m3"].items()}
        conf = b["confianza_m3"].fillna("baja")
        con_der = b["estado_derechos"] == "con_derechos"
        conf = peor(conf, b["confianza_cruce"].where(con_der, "alta").fillna("baja"))
        for i in b.index[con_der & (b["confianza_cruce"] != "alta")]:
            motivos[i].append(f"cruce_derechos_{b.at[i, 'confianza_cruce']}")
        reglas = [
            ("media", ~con_der, "sin_derechos_propios_ubicados"),
            ("baja", (b["m3_exceso_central"] > 0) & (b["m3_derecho_ajeno_disponible_500m"] >= b["m3_exceso_central"]),
             "derechos_ajenos_cubren_exceso"),
            ("media", ~b["temporada_completa"].fillna(False).astype(bool), "temporada_incompleta_m4"),
            ("media", b["clima_climatologia"].fillna(False).astype(bool), "clima_climatologia"),
            ("baja", sin_consumo, "sin_consumo_m4"),
        ]
        for nivel, mask, motivo in reglas:
            mask = mask.fillna(False)
            conf = bajar_a(conf, nivel, mask)
            for i in b.index[mask]:
                motivos[i].append(motivo)
        for i in b.index[b["canal_300m"].fillna(False).astype(bool)]:
            motivos[i].append("canal_300m")
        b["confianza"] = conf
        # Una alerta con confianza baja baja un nivel de banda: la banda alta exige confianza media o alta.
        bajar = (b["confianza"] == "baja") & (b["banda"] != "sin_alerta")
        b.loc[bajar, "banda"] = b.loc[bajar, "banda"].map({"alta": "media", "media": "baja", "baja": "sin_alerta"})
        b["motivos"] = pd.Series({i: ";".join(dict.fromkeys(";".join(m).split(";")) if m else "")
                                  for i, m in motivos.items()})
        b["motivos"] = b["motivos"].str.strip(";")

        # Puntaje.
        pct = b.groupby("zona")["m3_exceso_central"].rank(pct=True, method="average")
        pct = pct.where(b["m3_exceso_central"] > 0, 0.0)
        b["puntaje"] = (b["banda"].map(BASE_BANDA)
                        + 25 * b["frac_senal"].fillna(0) * b["confianza"].map(PESO_CONFIANZA) * pct).round(2)
        b["fiscalizado_dga"] = b["predio_id"].isin(fisc)
        b["_ob"] = b["banda"].map(ORDEN_BANDA)
        b = b.sort_values(["zona", "_ob", "puntaje", "m3_exceso_central", "predio_id"],
                          ascending=[True, True, False, False, True])
        b["rank_zona"] = b.groupby("zona").cumcount() + 1
        salidas.append(b.drop(columns=["_ob", "motivos_m3", "corte"]))

    if not salidas:
        sys.exit("Sin temporadas en común entre la señal y predio_derecho")
    out = pd.concat(salidas, ignore_index=True)
    orden = ["predio_id", "zona", "comuna", "temporada", "rank_zona", "banda", "puntaje", "confianza", "motivos",
             "senal_riego", "frac_senal", "n_fechas_validas", "z_verdor_mediana", "z_humedad_mediana", "ndvi_mediana",
             "ndmi_mediana", "area_ha", "especie_principal", "frac_fruticola", "predio_grande",
             "m3_consumo_bruto_min", "m3_consumo_bruto_central", "m3_consumo_bruto_max", "m3_derecho_asignado",
             "m3_exceso_min", "m3_exceso_central", "m3_exceso_max", "frac_sin_derecho",
             "m3_derecho_ajeno_disponible_500m", "m3_anual_derecho_entorno_500m", "pozo_compartido_500m",
             "estado_derechos", "confianza_cruce", "confianza_m3", "canal_300m", "dist_canal_m", "rol_id",
             "area_rol_ha", "temporada_completa", "fiscalizado_dga"]
    out = out[orden]
    destino = ruta(args.salida)
    out.to_parquet(destino, index=False)

    print(f"-> {destino}: {len(out)} filas, {out['predio_id'].nunique()} predios, temporadas "
          f"{', '.join(sorted(out['temporada'].unique()))}")
    for t, g in out.groupby("temporada"):
        print(f"\n{t}")
        tab = pd.crosstab(g["banda"], g["zona"], margins=True).reindex(list(ORDEN_BANDA) + ["All"])
        print(tab.to_string())
        print(pd.crosstab(g["banda"], g["confianza"]).reindex(list(ORDEN_BANDA)).to_string())
        al = g[g["banda"].isin(["alta", "media"])]
        print(f"Exceso alta+media: {al['m3_exceso_min'].sum() / 1e6:,.1f} – {al['m3_exceso_central'].sum() / 1e6:,.1f}"
              f" – {al['m3_exceso_max'].sum() / 1e6:,.1f} millones de m³/año (mín – central – máx); "
              f"con canal a 300 m: {al['canal_300m'].mean():.0%}; ya fiscalizados: {al['fiscalizado_dga'].sum()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
