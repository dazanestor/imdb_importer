# List Importer

List Importer es una aplicación web que permite sincronizar y agregar automáticamente películas y series populares desde IMDb a Radarr y Sonarr. Esta aplicación está desarrollada con Flask y Celery para la sincronización automática y periódica de contenidos.

## Características

- Sincronización automática de películas y series populares desde IMDb.
- Filtrado de películas y series basado en año y calificación.
- Verificación de listas de exclusión en Radarr y Sonarr antes de la importación.
- Interfaz web para configurar parámetros de sincronización y visualización del estado de la importación.

## Requisitos

- Docker
- Docker Compose

## Configuración

La configuración de las URLs y claves API para Radarr, Sonarr y TMDB se realiza a través de variables de entorno. Los otros parámetros de configuración (filtros de años, calificación, rutas de carpetas y perfiles de calidad) se manejan a través de la interfaz web.

### Variables de Entorno

Asegúrate de definir las siguientes variables de entorno en tu archivo `docker-compose.yml` o en tu entorno de ejecución:

- `RADARR_URL`: URL de tu instancia de Radarr.
- `RADARR_API_KEY`: Clave API de Radarr.
- `SONARR_URL`: URL de tu instancia de Sonarr.
- `SONARR_API_KEY`: Clave API de Sonarr.
- `TMDB_API_KEY`: Clave API de TMDB.
- `REDIS_IP`: Dirección IP de Redis (por defecto es `redis`).
## Instalación

### Instalación con Docker Compose

1. Clona el repositorio:

    ```bash
    git clone https://github.com/dazanestor/list_importer.git
    cd imdb_importer
    ```

2. Crea un archivo `docker-compose.yml` en el directorio raíz del proyecto con el siguiente contenido:

    ```yaml
    version: '3'
    services:
      web:
        build: .
        ports:
          - "5000:5000"
        environment:
          RADARR_URL: ${RADARR_URL:-http://localhost:7878}
          RADARR_API_KEY: ${RADARR_API_KEY:-your_radarr_api_key}
          SONARR_URL: ${SONARR_URL:-http://localhost:8989}
          SONARR_API_KEY: ${SONARR_API_KEY:-your_sonarr_api_key}
          TMDB_API_KEY: ${TMDB_API_KEY:-your_tmdb_api_key}
          REDIS_IP: ${REDIS_IP:-redis_ip}
        depends_on:
          - redis
          - worker

      worker:
        build:
          context: .
          dockerfile: Dockerfile.celery
        environment:
          RADARR_URL: ${RADARR_URL:-http://localhost:7878}
          RADARR_API_KEY: ${RADARR_API_KEY:-your_radarr_api_key}
          SONARR_URL: ${SONARR_URL:-http://localhost:8989}
          SONARR_API_KEY: ${SONARR_API_KEY:-your_sonarr_api_key}
          TMDB_API_KEY: ${TMDB_API_KEY:-your_tmdb_api_key}
          REDIS_IP: ${REDIS_IP:-redis}
        depends_on:
          - redis
    
      redis:
        image: "redis:alpine"
        ports:
          - "6379:6379"
    ```

3. Construye e inicia los servicios con Docker Compose:

    ```bash
    docker-compose up --build
    ```

4. Accede a la aplicación web en tu navegador:

    ```
    http://localhost:5000
    ```

### Instalación Manual

1. Clona el repositorio:

    ```bash
    git clone https://github.com/dazanestor/imdb_importer.git
    cd imdb_importer
    ```

2. Crea y activa un entorno virtual:

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3. Instala las dependencias:

    ```bash
    pip install -r requirements.txt
    ```

4. Configura Redis e inicia el servidor Redis:

    ```bash
    redis-server
    ```

5. Crea el archivo de configuración `config.json` en el directorio raíz del proyecto con el siguiente contenido:

    ```json
    {
        "movies_min_year": 2000,
        "movies_max_year": 2024,
        "movies_min_rating": 7.0,
        "series_min_year": 2000,
        "series_max_year": 2024,
        "series_min_rating": 7.0,
        "radarr_quality_profile_id": 1,
        "radarr_root_folder_path": "/path/to/radarr/movies",
        "sonarr_quality_profile_id": 1,
        "sonarr_root_folder_path": "/path/to/sonarr/series",
    }
    ```

6. Inicia la aplicación Flask:

    ```bash
    python app.py
    ```

7. Inicia el worker de Celery para la sincronización automática:

    ```bash
    celery -A tasks worker --loglevel=info
    celery -A tasks beat --loglevel=info
    ```

8. Accede a la aplicación web en tu navegador:

    ```
    http://localhost:5000
    ```

## Uso

1. Configura los parámetros de sincronización en la interfaz web y guarda la configuración.

2. Puedes iniciar manualmente la sincronización de películas y series desde la interfaz web o esperar a que se ejecuten automáticamente cada 12 horas.

## Estructura del Proyecto

- `app.py`: Archivo principal de la aplicación Flask.
- `tasks.py`: Definición de tareas de Celery para la sincronización de películas y series.
- `templates/`: Directorio que contiene las plantillas HTML para la interfaz web.
- `static/`: Directorio que contiene los archivos estáticos (CSS, JS, imágenes).
- `config.json`: Archivo de configuración para la aplicación.
- `docker-compose.yml`: Archivo de configuración para Docker Compose.

## Contribución

Si deseas contribuir a este proyecto, por favor realiza un fork del repositorio, crea una rama con tus cambios y envía un pull request.

## Licencia

Este proyecto está licenciado bajo la Licencia GPL. Ver el archivo `LICENSE` para más detalles.
