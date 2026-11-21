# Caudal · frontend estático servido con nginx (Cloud Run: `gcloud run deploy caudal-web --source frontend-demo`).
# No hay build: la imagen es la carpeta tal cual más la configuración de nginx.
FROM nginx:1.27-alpine

# Cloud Run entrega el puerto en PORT (8080). La imagen de nginx reemplaza ${PORT} en las plantillas al arrancar.
ENV PORT=8080
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY . /usr/share/nginx/html

EXPOSE 8080
