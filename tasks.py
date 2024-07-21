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
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    script = soup.find('script', type='application/ld+json')
    
    if script is None:
        raise Exception("No se encontró el script JSON-LD en la página")

    data = json.loads(script.string)
    items = [
        {
            "title": item['item']['name'],
            "rating": float(item['item']['aggregateRating']['ratingValue'])
        }
        for item in data.get('itemListElement', [])
        if item['item'].get('name') and item['item'].get('aggregateRating', {}).get('ratingValue')
    ]

    return items

def fetch_item_year_tmdb(title, tmdb_api_key, media_type):
    url = f"https://api.themoviedb.org/3/search/{media_type}?api_key={tmdb_api_key}&query={requests.utils.quote(title)}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        results = data['results']
        if results:
            return results[0].get('release_date', '').split('-')[0] if media_type == 'movie' else results[0].get('first_air_date', '').split('-')[0]
    return None

def filter_items(items, min_year, max_year, min_rating, tmdb_api_key, media_type):
    def is_valid(item):
        year = fetch_item_year_tmdb(item['title'], tmdb_api_key, media_type)
        if year:
            logger.info(f"Item: {item['title']}, Year: {year}, Rating: {item['rating']}")
            return min_year <= int(year) <= max_year and item['rating'] >= min_rating
        else:
            logger.warning(f"Year not found for {item['title']}")
            return False

    return [item for item in items if is_valid(item)]

def process_items(items, add_function):
    with ThreadPoolExecutor() as executor:
        return list(executor.map(add_function, items))

def check_excluded(title, excluded_titles):
    excluded = title.lower() in (excluded.lower() for excluded in excluded_titles)
    if excluded:
        logger.info(f"Excluded: {title}")
    return excluded

def get_excluded_titles_from_endpoint(base_url, api_key, media_type):
    endpoint = f"{base_url}/api/v3/exclusions" if media_type == 'movie' else f"{base_url}/api/v3/importlistexclusion/paged"
    headers = {"X-Api-Key": api_key}
    excluded_titles = []

    logger.info(f"Fetching exclusions from {endpoint}")

    response = requests.get(endpoint, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to fetch exclusions: {response.status_code} {response.text}")
        return excluded_titles

    logger.debug(f"Raw exclusions response: {response.text}")

    try:
        exclusions = response.json()
        logger.debug(f"Parsed exclusions: {exclusions}")
        if media_type == 'movie':
            excluded_titles = [movie['movieTitle'] for movie in exclusions]
        else:
            excluded_titles = [series['title'] for series in exclusions['records']]
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")

    logger.debug(f"Excluded titles from {media_type}: {excluded_titles}")
    return excluded_titles

def fetch_tmdb_id(title, tmdb_api_key):
    url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={requests.utils.quote(title)}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['results']:
            return data['results'][0]['id']
    return None

def add_movie_to_radarr(movie, radarr_url, radarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key):
    logger.info(f"Attempting to add movie to Radarr: {movie['title']}")
    headers = {"X-Api-Key": radarr_api_key}
    tmdb_id = movie.get('tmdb_id') or fetch_tmdb_id(movie['title'], tmdb_api_key)

    if not tmdb_id:
        logger.error(f"TmdbId not found for movie: {movie['title']}")
        return {"title": movie['title'], "exists": False}

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

    try:
        response = requests.post(f"{radarr_url}/api/v3/movie", json=payload, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 400 and "MovieExistsValidator" in response.text:
            logger.info(f"Movie already exists according to Radarr: {movie['title']}")
            return {"title": movie['title'], "exists": True}
        else:
            logger.error(f"HTTP error occurred: {http_err}")
            logger.error(f"Response text: {response.text}")
            raise

    logger.info(f"Successfully added movie to Radarr: {movie['title']}")
    return {"title": movie['title'], "exists": False}

def fetch_series_from_tmdb(title, tmdb_api_key):
    url = f"https://api.themoviedb.org/3/search/tv?api_key={tmdb_api_key}&query={requests.utils.quote(title)}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['results']:
            return data['results'][0]
    return None

def fetch_tvdb_id_from_tmdb_id(tmdb_id, tmdb_api_key):
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids?api_key={tmdb_api_key}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('tvdb_id')
    return None

def fetch_tvdb_id(title, tmdb_api_key):
    series = fetch_series_from_tmdb(title, tmdb_api_key)
    if series:
        tmdb_id = series.get('id')
        return fetch_tvdb_id_from_tmdb_id(tmdb_id, tmdb_api_key)
    return None

def add_to_sonarr(serie, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key):
    logger.info(f"Attempting to add series to Sonarr: {serie['title']}")
    headers = {"X-Api-Key": sonarr_api_key}
    tvdb_id = serie.get('tvdb_id') or fetch_tvdb_id(serie['title'], tmdb_api_key)

    if not tvdb_id:
        logger.error(f"TvdbId not found for series: {serie['title']}")
        return {"title": serie['title'], "exists": False}

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

    try:
        response = requests.post(f"{sonarr_url}/api/v3/series", json=payload, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 400 and "SeriesExistsValidator" in response.text:
            logger.info(f"Series already exists according to Sonarr: {serie['title']}")
            return {"title": serie['title'], "exists": True}
        else:
            logger.error(f"HTTP error occurred: {http_err}")
            logger.error(f"Response text: {response.text}")
            raise

    logger.info(f"Successfully added series to Sonarr: {serie['title']}")
    return {"title": serie['title'], "exists": False}

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

    try:
        excluded_movies = get_excluded_titles_from_endpoint(radarr_url, radarr_api_key, 'movie')
        logger.info(f"Películas excluidas obtenidas: {excluded_movies}")
    except Exception as e:
        logger.error(f"Error fetching excluded movies list: {e}")
        return

    filtered_movies = filter_items(movies_list, movies_min_year, movies_max_year, movies_min_rating, tmdb_api_key, 'movie')
    filtered_movies = [movie for movie in filtered_movies if not check_excluded(movie['title'], excluded_movies)]

    logger.debug(f"Filtered movies: {filtered_movies}")

    imported_movies = process_items(filtered_movies, lambda movie: add_movie_to_radarr(movie, radarr_url, radarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key))
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

    try:
        excluded_series = get_excluded_titles_from_endpoint(sonarr_url, sonarr_api_key, 'series')
        logger.info(f"Series excluidas obtenidas: {excluded_series}")
    except Exception as e:
        logger.error(f"Error fetching excluded series list: {e}")
        return
    
    filtered_series = filter_items(series_list, series_min_year, series_max_year, series_min_rating, tmdb_api_key, 'tv')
    filtered_series = [series for series in filtered_series if not check_excluded(series['title'], excluded_series)]

    imported_series = process_items(filtered_series, lambda series: add_to_sonarr(series, sonarr_url, sonarr_api_key, quality_profile_id, root_folder_path, tmdb_api_key))
    imported_series = [series['title'] for series in imported_series if not series['exists']]
    r.set('imported_series', json.dumps(imported_series))
    logger.info(f"Series importadas: {imported_series}")
