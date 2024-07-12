# Dockerfile

# Usar una imagen base de Python
FROM python:3.9-slim

# Establecer el directorio de trabajo en el contenedor
WORKDIR /app

# Copiar el archivo requirements.txt al contenedor
COPY requirements.txt requirements.txt

# Instalar las dependencias del proyecto
RUN pip install -r requirements.txt

# Copiar el resto de los archivos de la aplicación al contenedor
COPY . .

# Exponer el puerto en el que la aplicación Flask se ejecutará
EXPOSE 5000

# Comando para ejecutar la aplicación
CMD ["python", "app.py"]
