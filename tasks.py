from celery import Celery
from datetime import timedelta
import requests
import json
from concurrent.futures import ThreadPoolExecutor

app = Celery('tasks', broker='redis://localhost:6379/0')
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

def read_config():
    with open('config.json', 'r') as f:
        return json.load(f)

@app.task
def run_sync_movies():
    config = read_config()
    imdb_list_url = config['imdb_list_url']
    radarr_api_key = config['radarr_api_key']
    movies_min_year = config['movies_min_year']
    movies_max_year = config['movies_max_year']
    movies_min_rating = config['movies_min_rating']

    imdb_list = fetch_imdb_list(imdb_list_url)

    movies = [item for item in imdb_list if item['type'] == 'movie']
    filtered_movies = filter_movies(movies, movies_min_year, movies_max_year, movies_min_rating)

    with ThreadPoolExecutor() as executor:
        results = executor.map(lambda movie: add_to_radarr(movie, radarr_api_key), filtered_movies)

@app.task
def run_sync_series():
    config = read_config()
    imdb_list_url = config['imdb_list_url']
    sonarr_api_key = config['sonarr_api_key']
    series_min_year = config['series_min_year']
    series_max_year = config['series_max_year']
    series_min_rating = config['series_min_rating']

    imdb_list = fetch_imdb_list(imdb_list_url)

    series = [item for item in imdb_list if item['type'] == 'series']
    filtered_series = filter_series(series, series_min_year, series_max_year, series_min_rating)

    with ThreadPoolExecutor() as executor:
        results = executor.map(lambda serie: add_to_sonarr(serie, sonarr_api_key), filtered_series)

def fetch_imdb_list(list_url):
    response = requests.get(list_url)
    return response.json()

def filter_movies(movies, min_year, max_year, min_rating):
    return [movie for movie in movies if min_year <= movie['year'] <= max_year and movie['rating'] >= min_rating]

def filter_series(series, min_year, max_year, min_rating):
    return [serie for serie in series if min_year <= serie['year'] <= max_year and serie['rating'] >= min_rating]

def add_to_radarr(movie, radarr_api_key):
    payload = {
        "title": movie['title'],
        "year": movie['year'],
        "tmdbId": movie['tmdb_id'],
        "qualityProfileId": 1,
        "titleSlug": movie['title'].lower().replace(' ', '-'),
        "monitored": True,
        "rootFolderPath": "/movies",
        "addOptions": {
            "searchForMovie": True
        }
    }
    headers = {"X-Api-Key": radarr_api_key}
    response = requests.post(f"http://localhost:7878/api/v3/movie", json=payload, headers=headers)
    return response.status_code

def add_to_sonarr(serie, sonarr_api_key):
    payload = {
        "title": serie['title'],
        "year": serie['year'],
        "tvdbId": serie['tvdb_id'],
        "qualityProfileId": 1,
        "titleSlug": serie['title'].lower().replace(' ', '-'),
        "monitored": True,
        "rootFolderPath": "/series",
        "addOptions": {
            "searchForSeries": True
        }
    }
    headers = {"X-Api-Key": sonarr_api_key}
    response = requests.post(f"http://localhost:8989/api/v3/series", json=payload, headers=headers)
    return response.status_code
