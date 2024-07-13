import requests
from bs4 import BeautifulSoup
from celery import Celery
from datetime import timedelta
import json
from concurrent.futures import ThreadPoolExecutor
import redis
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_celery_app(redis_ip):
    return Celery('tasks', broker=f'redis://{redis_ip}:6379/0')

def read_config():
    with open('config.json', 'r') as f:
        return json.load(f)

config = read_config()
app = create_celery_app(config['redis_ip'])
r = redis.Redis(host=config['redis_ip'], port=6379, db=0)

app.conf.beat_schedule = {
    'run-sync-movies-every-12-hours': {
        'task': 'tasks.run_sync_movies',
        'schedule': timedelta(hours=12),
    },
    'run-sync-series-every-12-hours': {
        'task': 'tasks.run_sync_series',
        'schedule': timedelta(hours=12),
    },
}
app.conf.timezone = 'UTC'

def fetch_imdb_list(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching IMDb list: {response.status_code} {response.reason}")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    items = []

    for item in soup.select('table.chart.full-width tr'):
        title_column = item.select('td.titleColumn')
        rating_column = item.select('td.imdbRating')

        if title_column and rating_column:
            title = title_column[0].a.text
            year = title_column[0].span.text.strip('()')
            rating = rating_column[0].strong.text if rating_column[0].strong else None
            
            items.append({
                "title": title,
                "year": int(year),
                "rating": float(rating) if rating else None
            })

    return items

def filter_items(items, min_year, max_year, min_rating):
    return [item for item in items if min_year <= item['year'] <= max_year and (item['rating'] is None or item['rating'] >= min_rating)]

def process_items(items, url, api_key, quality_profile_id, root_folder_path, add_function):
    with ThreadPoolExecutor() as executor:
        results = executor.map(lambda item: add_function(item, url, api_key, quality_profile_id, root_folder_path), items)
        return [result['title'] for result in results if result]

@app.task
def run_sync_movies():
    config = read_config()
    radarr_url = config['radarr_url']
    radarr_api_key = config['radarr_api_key']
    quality_profile_id = config['radarr_quality_profile_id']
    root_folder_path = config['radarr_root_folder_path']
    movies_min_year = config['movies_min_year']
    movies_max_year = config['movies_max_year']
    movies_min_rating = config['movies_min_rating']

    try:
        logger.info("Obteniendo lista de películas de IMDb...")
        movies_list = fetch_imdb_list('https://www.imdb.com/chart/moviemeter/')
    except Exception as e:
        logger.error(f"Error fetching IMDb movies list: {e}")
        return

    filtered_movies = filter_items(movies_list, movies_min_year, movies_max_year, movies_min_rating)
    imported_movies = process_items(filtered_movies, radarr_url, radarr_api_key, quality_profile_id, root_folder_path, add_to_radarr)
    r.set('imported_movies', json.dumps(imported_movies))
    logger.info(f"Películas importadas: {imported_movies}")

@app.task
def run_sync_series():
    config = read_config()
    sonarr_url = config['sonarr_url']
    sonarr_api_key = config['sonarr_api_key']
    quality_profile_id = config['sonarr_quality_profile_id']
    root_folder_path = config['sonarr_root_folder_path']
    series_min_year = config['series_min_year']
    series_max_year = config['series_max_year']
    series_min_rating = config['series_min_rating']

    try:
        logger.info("Obteniendo lista de series de IMDb...")
        series_list = fetch_imdb_list('https://www.imdb.com/chart/tvmeter/')
    except Exception as e:
        logger.error(f"Error fetching IMDb series list: {e}")
        return

    filtered_series = filter_items(series_list, series_min_year, series_max_year, series_min_rating)
    imported_series = process_items(filtered_series, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path, add_to_sonarr)
    r.set('imported_series', json.dumps(imported_series))
    logger.info(f"Series importadas: {imported_series}")

def add_to_radarr(movie, radarr_url, radarr_api_key, quality_profile_id, root_folder_path):
    payload = {
        "title": movie['title'],
        "year": movie['year'],
        "tmdbId": movie.get('tmdb_id', 0),  # Asegúrate de tener el ID correcto aquí
        "qualityProfileId": quality_profile_id,
        "titleSlug": movie['title'].lower().replace(' ', '-'),
        "monitored": True,
        "rootFolderPath": root_folder_path,
        "addOptions": {
            "searchForMovie": True
        }
    }
    headers = {"X-Api-Key": radarr_api_key}

    # Verifica si la película ya está en Radarr
    response = requests.get(f"{radarr_url}/api/v3/movie/lookup?term={payload['title']}", headers=headers)
    if response.status_code == 200 and response.json():
        logger.info(f"Película ya existe en Radarr: {payload['title']}")
        return payload

    response = requests.post(f"{radarr_url}/api/v3/movie", json=payload, headers=headers)
    if response.status_code != 201:
        raise Exception(f"Error adding to Radarr: {response.status_code} {response.reason}")
    return payload

def add_to_sonarr(serie, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path):
    payload = {
        "title": serie['title'],
        "year": serie['year'],
        "tvdbId": serie.get('tvdb_id', 0),  # Asegúrate de tener el ID correcto aquí
        "qualityProfileId": quality_profile_id,
        "titleSlug": serie['title'].lower().replace(' ', '-'),
        "monitored": True,
        "rootFolderPath": root_folder_path,
        "addOptions": {
            "searchForSeries": True
        }
    }
    headers = {"X-Api-Key": sonarr_api_key}

    # Verifica si la serie ya está en Sonarr
    response = requests.get(f"{sonarr_url}/api/v3/series/lookup?term={payload['title']}", headers=headers)
    if response.status_code == 200 and response.json():
        logger.info(f"Serie ya existe en Sonarr: {payload['title']}")
        return payload

    response = requests.post(f"{sonarr_url}/api/v3/series", json=payload, headers=headers)
    if response.status_code != 201:
        raise Exception(f"Error adding to Sonarr: {response.status_code} {response.reason}")
    return payload
