FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

COPY . .

# Copia un archivo de configuración por defecto al contenedor
COPY config.json /app/config/config.json.default

# Añade un script de inicio para copiar config.json si no existe
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000

# Define el comando de inicio usando el script de entrada
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "app.py"]
