# Usa una imagen base de Python
FROM python:3.9-slim

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos de requisitos y el código fuente de la aplicación
COPY requirements.txt requirements.txt
COPY . .

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copia un archivo de configuración por defecto al contenedor
COPY config.json /app/config/config.json.default

# Añade un script de inicio para copiar config.json si no existe

# Expone el puerto en el que correrá la aplicación
EXPOSE 5000

# Define el comando de inicio usando el script de entrada
CMD ["python", "app.py"]
