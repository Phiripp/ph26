#!/usr/bin/env bash
# Prueba las rutas de caudal-api contra una URL: código HTTP, segundos y bytes de cada una. Sale con error si alguna
# no responde lo esperado. El predio y el caso salen de /api/demo (data/demo.json).
# Uso: scripts/cloud/api/probar.sh [URL]        por defecto http://localhost:8000
#      EXPEDIENTE=1 scripts/cloud/api/probar.sh URL    además pide el expediente del candidato y baja el PDF
set -uo pipefail
API=${1:-http://localhost:8000}
API=${API%/}
fallas=0

prueba() {  # prueba ESPERADO RUTA
  local r
  r=$(curl -s -o /dev/null -m 30 -w '%{http_code} %{time_total} %{size_download}' "$API$2")
  if [ "${r%% *}" = "$1" ]; then echo "ok    $r  $2"; else echo "FALLA $r  $2 (esperaba $1)"; fallas=$((fallas + 1)); fi
}

demo=$(curl -s -m 30 "$API/api/demo") || { echo "FALLA: $API no responde"; exit 1; }
leer() { python3 -c "import json,sys; print(json.load(sys.stdin)['$1'])" <<<"$demo"; }
ZONA=$(leer zona); CASO=$(leer caso); PREDIO=$(leer candidato)

for r in /api/health /api/demo /api/impacto /api/zonas /api/casos "/api/casos/$CASO" \
         "/api/zonas/$ZONA/resumen" "/api/zonas/$ZONA/ranking" "/api/zonas/$ZONA/ranking?banda=alta&sin_canal=true&sin_fiscalizar=true" \
         "/api/zonas/$ZONA/predios" "/api/zonas/$ZONA/ruta" "/api/zonas/$ZONA/ruta.gpx" "/api/zonas/$ZONA/ruta.geojson" \
         "/api/predios/$PREDIO" "/api/predios/$PREDIO/serie"; do
  prueba 200 "$r"
done
# Corrida nacional: estrictas solo si /api/health dice nacional.disponible; si no, 503 es lo esperado.
if python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('nacional', {}).get('disponible') else 1)" < <(curl -s -m 30 "$API/api/health"); then
  REGION_N=$(curl -s -m 30 "$API/api/chile" | python3 -c "import json,sys; print(json.load(sys.stdin)['regiones'][0]['zona'])")
  prueba 200 /api/chile
  prueba 200 "/api/chile/$REGION_N/ranking?banda=alta&limite=5"
  prueba 200 "/api/chile/predios/$PREDIO"
  prueba 404 /api/chile/predios/1
  prueba 404 /api/chile/R99/ranking
else
  echo "aviso: corrida nacional no disponible (sin CAUDAL_NACIONAL o sin montaje): /api/chile debe dar 503"
  prueba 503 /api/chile
fi
prueba 404 /api/predios/1
prueba 404 /api/zonas/Z9/resumen
prueba 404 /api/casos/NO-EXISTE
prueba 422 "/api/predios/$PREDIO?temporada=1999-00"
prueba 404 /api/expediente/CAU-1-000000000000/expediente.pdf

if [ -n "${EXPEDIENTE:-}" ]; then
  e=$(curl -s -m 90 -w ' %{time_total}' -X POST "$API/api/expediente" -H 'content-type: application/json' -d "{\"predio_id\": $PREDIO}")
  echo "expediente: $e"
  url=$(python3 -c "import json,sys; print(json.loads(sys.stdin.read().rsplit(' ', 1)[0])['url_pdf'])" <<<"$e") || fallas=$((fallas + 1))
  [ -n "${url:-}" ] && prueba 200 "$url"
fi

[ "$fallas" = 0 ] && echo "Todo bien: $API" || { echo "$fallas fallas en $API"; exit 1; }
