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

    script = soup.find('script', type='application/ld+json')
    if script is None:
        raise Exception("No se encontró el script JSON-LD en la página")

    data = json.loads(script.string)
    items = []

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
        if year:
            logger.info(f"Item: {item['title']}, Year: {year}, Rating: {item['rating']}")
            if min_year <= int(year) <= max_year and item['rating'] >= min_rating:
                filtered_items.append(item)
        else:
            logger.warning(f"Year not found for {item['title']}")
    return filtered_items

def process_items(items, url, api_key, quality_profile_id, root_folder_path, add_function):
    with ThreadPoolExecutor() as executor:
        results = executor.map(add_function, items)
        return [result for result in results if result]

def check_excluded(title, excluded_titles):
    return title.lower() in (excluded.lower() for excluded in excluded_titles)

def get_excluded_titles(url, api_key, media_type):
    headers = {"X-Api-Key": api_key}
    endpoint = f"{url}/api/v3/{'movie' if media_type == 'movie' else 'series'}"
    response = requests.get(endpoint, headers=headers)
    if response.status_code == 200:
        return [item['title'] for item in response.json() if item['monitored'] == False]
    return []

def fetch_tmdb_id(title, tmdb_api_key):
    url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={requests.utils.quote(title)}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['results']:
            return data['results'][0]['id']
    logger.warning(f"TMDb ID not found for title: {title}")
    return None

def add_to_radarr(movie, radarr_url, radarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key):
    logger.info(f"Attempting to add movie to Radarr: {movie['title']}")
    headers = {"X-Api-Key": radarr_api_key}

    # Buscar la película por título
    response = requests.get(f"{radarr_url}/api/v3/movie/lookup?term={requests.utils.quote(movie['title'])}", headers=headers)
    if response.status_code == 200:
        existing_movies = response.json()
        logger.debug(f"Lookup response: {existing_movies}")
        for existing_movie in existing_movies:
            if existing_movie['title'].lower() == movie['title'].lower() or existing_movie['tmdbId'] == movie.get('tmdb_id'):
                logger.info(f"Movie already exists in Radarr: {movie['title']}")
                return {"title": movie['title'], "exists": True}

    # Obtener el TmdbId si no está presente
    tmdb_id = movie.get('tmdb_id')
    if not tmdb_id or tmdb_id == 0:
        tmdb_id = fetch_tmdb_id(movie['title'], tmdb_api_key)
        if not tmdb_id:
            logger.error(f"TmdbId not found for movie: {movie['title']}")
            return {"title": movie['title'], "exists": False}

    # Añadir la película si no existe
    payload = {
        "title": movie['title'],
        "year": int(movie.get('year', 0)),
        "tmdbId": tmdb_id,
        "qualityProfileId": quality_profile_id,
        "titleSlug": movie['title'].lower().replace(' ', '-'),
        "monitored": True,
        "rootFolderPath": root_folder_path,
        "addOptions": {
            "searchForMovie": True
        }
    }

    logger.debug(f"Payload for adding movie to Radarr: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(f"{radarr_url}/api/v3/movie", json=payload, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 400 and "MovieExistsValidator" in response.text:
            logger.info(f"Movie already exists according to Radarr: {movie['title']}")
            return {"title": movie['title'], "exists": True}
        else:
            logger.error(f"HTTP error occurred: {http_err}")
            raise

    logger.info(f"Successfully added movie to Radarr: {movie['title']}")
    return {"title": movie['title'], "exists": False}

def add_movie_to_radarr(movie, radarr_url, radarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key):
    return add_to_radarr(movie, radarr_url, radarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key)

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

    excluded_movies = get_excluded_titles(radarr_url, radarr_api_key, 'movie')
    filtered_movies = filter_items(movies_list, movies_min_year, movies_max_year, movies_min_rating, tmdb_api_key, 'movie')
    filtered_movies = [movie for movie in filtered_movies if not check_excluded(movie['title'], excluded_movies)]

    imported_movies = process_items(filtered_movies, radarr_url, radarr_api_key, quality_profile_id, root_folder_path, lambda movie: add_movie_to_radarr(movie, radarr_url, radarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key))
    imported_movies = [movie['title'] for movie in imported_movies if not movie['exists']]
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

    excluded_series = get_excluded_titles(sonarr_url, sonarr_api_key, 'tv')
    filtered_series = filter_items(series_list, series_min_year, series_max_year, series_min_rating, tmdb_api_key, 'tv')
    filtered_series = [series for series in filtered_series if not check_excluded(series['title'], excluded_series)]

    imported_series = process_items(filtered_series, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path, lambda series: add_to_sonarr(series, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key))
    imported_series = [series['title'] for series in imported_series if not series['exists']]
    r.set('imported_series', json.dumps(imported_series))
    logger.info(f"Series importadas: {imported_series}")

def add_to_sonarr(serie, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key):
    logger.info(f"Attempting to add series to Sonarr: {serie['title']}")
    headers = {"X-Api-Key": sonarr_api_key}

    # Buscar la serie por título
    response = requests.get(f"{sonarr_url}/api/v3/series/lookup?term={requests.utils.quote(serie['title'])}", headers=headers)
    if response.status_code == 200:
        existing_series = response.json()
        for existing_serie in existing_series:
            if existing_serie['title'].lower() == serie['title'].lower():
                logger.info(f"Series already exists in Sonarr: {serie['title']}")
                return {"title": serie['title'], "exists": True}

    # Obtener el TvdbId si no está presente
    tvdb_id = serie.get('tvdb_id')
    if not tvdb_id or tvdb_id == 0:
        tvdb_id = fetch_tvdb_id(serie['title'], tmdb_api_key)
        if not tvdb_id:
            logger.error(f"TvdbId not found for series: {serie['title']}")
            return {"title": serie['title'], "exists": False}

    # Añadir la serie si no existe
    payload = {
        "title": serie['title'],
        "year": int(serie.get('year', 0)),
        "tvdbId": tvdb_id,
        "qualityProfileId": quality_profile_id,
        "titleSlug": serie['title'].lower().replace(' ', '-'),
        "monitored": True,
        "rootFolderPath": root_folder_path,
        "addOptions": {
            "searchForSeries": True
        }
    }

    logger.debug(f"Payload for adding series to Sonarr: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{sonarr_url}/api/v3/series", json=payload, headers=headers)
    if response.status_code == 409:
        logger.info(f"Series already exists (Conflict): {serie['title']}")
        return {"title": serie['title'], "exists": True}
    elif response.status_code != 201:
        logger.error(f"Error adding to Sonarr: {response.status_code} {response.reason} {response.text}")
        raise Exception(f"Error adding to Sonarr: {response.status_code} {response.reason} {response.text}")

    logger.info(f"Successfully added series to Sonarr: {serie['title']}")
    return {"title": serie['title'], "exists": False}
