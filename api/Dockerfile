# caudal-api: FastAPI + DuckDB sobre los Parquet de data/processed/ y el expediente PDF (WeasyPrint).
# No se construye desde la raíz del repo: scripts/cloud/api/desplegar.sh arma un contexto con api/, scripts/models/
# y los datos (incluido predio.parquet, que no está en git) y escribe data/VERSION.
FROM python:3.12-slim

# pango y harfbuzz: WeasyPrint. DejaVu: la fuente de la plantilla del expediente. tzdata: fechas en hora de Chile.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Santiago PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/matplotlib \
    CAUDAL_RAIZ=/app PORT=8080

WORKDIR /app
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY scripts/models scripts/models
COPY scripts/comun scripts/comun
COPY api api
COPY data data

# Expedientes de la demo, generados con los datos de esta imagen (necesita red; sin red salen sin imágenes).
RUN python -m api.pregenerar

# Los expedientes nuevos van a /tmp (en Cloud Run es memoria de la instancia; duran lo que dura la instancia).
ENV CAUDAL_EXPEDIENTES=/tmp/expedientes
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
