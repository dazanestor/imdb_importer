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

    # Encuentra el script que contiene el JSON-LD
    script = soup.find('script', type='application/ld+json')
    if script is None:
        raise Exception("No se encontró el script JSON-LD en la página")

    # Carga el JSON-LD
    data = json.loads(script.string)
    items = []

    # Extrae la información de las películas y series
    for item in data.get('itemListElement', []):
        media_item = item.get('item', {})
        title = media_item.get('name')
        rating = media_item.get('aggregateRating', {}).get('ratingValue')
        
        if title and rating:
            items.append({
                "title": title,
                "rating": float(rating)
            })

    return items

def fetch_item_year_tmdb(title, tmdb_api_key, media_type):
    url = f"https://api.themoviedb.org/3/search/{media_type}?api_key={tmdb_api_key}&query={requests.utils.quote(title)}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['results']:
            return data['results'][0].get('release_date', '').split('-')[0] if media_type == 'movie' else data['results'][0].get('first_air_date', '').split('-')[0]
    return None

def filter_items(items, min_year, max_year, min_rating, tmdb_api_key, media_type):
    filtered_items = []
    for item in items:
        year = fetch_item_year_tmdb(item['title'], tmdb_api_key, media_type)
        if year and min_year <= int(year) <= max_year and item['rating'] >= min_rating:
            filtered_items.append(item)
    return filtered_items

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
    tmdb_api_key = config['tmdb_api_key']

    try:
        logger.info("Obteniendo lista de películas de IMDb...")
        movies_list = fetch_imdb_list('https://www.imdb.com/chart/moviemeter/')
    except Exception as e:
        logger.error(f"Error fetching IMDb movies list: {e}")
        return

    filtered_movies = filter_items(movies_list, movies_min_year, movies_max_year, movies_min_rating, tmdb_api_key, 'movie')
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
    tmdb_api_key = config['tmdb_api_key']

    try:
        logger.info("Obteniendo lista de series de IMDb...")
        series_list = fetch_imdb_list('https://www.imdb.com/chart/tvmeter/')
    except Exception as e:
        logger.error(f"Error fetching IMDb series list: {e}")
        return

    filtered_series = filter_items(series_list, series_min_year, series_max_year, series_min_rating, tmdb_api_key, 'tv')
    imported_series = process_items(filtered_series, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path, add_to_sonarr)
    r.set('imported_series', json.dumps(imported_series))
    logger.info(f"Series importadas: {imported_series}")

def add_to_radarr(movie, radarr_url, radarr_api_key, quality_profile_id, root_folder_path):
    payload = {
        "title": movie['title'],
        "year": 0,  # Ya no se usa el año
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
        logger.error(f"Error adding to Radarr: {response.status_code} {response.reason} {response.text}")
        raise Exception(f"Error adding to Radarr: {response.status_code} {response.reason} {response.text}")
    return payload

def add_to_sonarr(serie, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path):
    payload = {
        "title": serie['title'],
        "year": 0,  # Ya no se usa el año
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
        logger.error(f"Error adding to Sonarr: {response.status_code} {response.reason} {response.text}")
        raise Exception(f"Error adding to Sonarr: {response.status_code} {response.reason} {response.text}")
    return payload
