#!/bin/sh

# Crea el directorio de configuración si no existe
mkdir -p /app/config

# Copia el archivo de configuración por defecto si no existe
if [ ! -f /app/config/config.json ]; then
  cp /app/config/config.json.default /app/config/config.json
fi
cp -R /app/config/config.json /app/config.json

exec "$@"
