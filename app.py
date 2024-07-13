from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from marshmallow import Schema, fields, ValidationError
import json
import requests
from tasks import run_sync_movies, run_sync_series
import redis
import logging

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Definición de schemas para validación
class ConfigSchema(Schema):
    radarr_url = fields.Url(required=True)
    radarr_api_key = fields.Str(required=True)
    sonarr_url = fields.Url(required=True)
    sonarr_api_key = fields.Str(required=True)
    movies_min_year = fields.Int(required=True)
    movies_max_year = fields.Int(required=True)
    movies_min_rating = fields.Float(required=True)
    series_min_year = fields.Int(required=True)
    series_max_year = fields.Int(required=True)
    series_min_rating = fields.Float(required=True)
    radarr_quality_profile_id = fields.Int(required=True)
    radarr_root_folder_path = fields.Str(required=True)
    sonarr_quality_profile_id = fields.Int(required=True)
    sonarr_root_folder_path = fields.Str(required=True)
    omdb_api_key = fields.Str(required=True)

def read_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def write_config(data):
    with open('config.json', 'w') as f:
        json.dump(data, f, indent=4)

def get_radarr_profiles_and_paths(radarr_url, radarr_api_key):
    headers = {"X-Api-Key": radarr_api_key}
    profiles = requests.get(f"{radarr_url}/api/v3/qualityProfile", headers=headers).json()
    paths = requests.get(f"{radarr_url}/api/v3/rootFolder", headers=headers).json()
    return profiles, paths

def get_sonarr_profiles_and_paths(sonarr_url, sonarr_api_key):
    headers = {"X-Api-Key": sonarr_api_key}
    profiles = requests.get(f"{sonarr_url}/api/v3/qualityProfile", headers=headers).json()
    paths = requests.get(f"{sonarr_url}/api/v3/rootFolder", headers=headers).json()
    return profiles, paths

config = read_config()
r = redis.Redis(host=config['redis_ip'], port=6379, db=0)

@app.route('/', methods=['GET', 'POST'])
def index():
    config = read_config()
    radarr_profiles, radarr_paths = [], []
    sonarr_profiles, sonarr_paths = [], []
    
    if config['radarr_api_key'] and config['radarr_url']:
        try:
            radarr_profiles, radarr_paths = get_radarr_profiles_and_paths(config['radarr_url'], config['radarr_api_key'])
        except requests.exceptions.RequestException as e:
            flash(f"Error al obtener perfiles y rutas de Radarr: {str(e)}")
    
    if config['sonarr_api_key'] and config['sonarr_url']:
        try:
            sonarr_profiles, sonarr_paths = get_sonarr_profiles_and_paths(config['sonarr_url'], config['sonarr_api_key'])
        except requests.exceptions.RequestException as e:
            flash(f"Error al obtener perfiles y rutas de Sonarr: {str(e)}")
    
    imported_movies = json.loads(r.get('imported_movies') or '[]')
    imported_series = json.loads(r.get('imported_series') or '[]')

    if request.method == 'POST':
        form_data = {
            "radarr_url": request.form['radarr_url'],
            "radarr_api_key": request.form['radarr_api_key'],
            "sonarr_url": request.form['sonarr_url'],
            "sonarr_api_key": request.form['sonarr_api_key'],
            "movies_min_year": int(request.form['movies_min_year']),
            "movies_max_year": int(request.form['movies_max_year']),
            "movies_min_rating": float(request.form['movies_min_rating']),
            "series_min_year": int(request.form['series_min_year']),
            "series_max_year": int(request.form['series_max_year']),
            "series_min_rating": float(request.form['series_min_rating']),
            "radarr_quality_profile_id": int(request.form['radarr_quality_profile_id']),
            "radarr_root_folder_path": request.form['radarr_root_folder_path'],
            "sonarr_quality_profile_id": int(request.form['sonarr_quality_profile_id']),
            "sonarr_root_folder_path": request.form['sonarr_root_folder_path'],
            "omdb_api_key": request.form['omdb_api_key']
        }
        schema = ConfigSchema()
        try:
            config = schema.load(form_data)
            write_config(config)
            flash('Configuración guardada exitosamente!')
            return redirect(url_for('index'))
        except ValidationError as err:
            flash(f"Errores de validación: {err.messages}")
    
    return render_template('index.html', config=config, radarr_profiles=radarr_profiles, radarr_paths=radarr_paths, sonarr_profiles=sonarr_profiles, sonarr_paths=sonarr_paths, imported_movies=imported_movies, imported_series=imported_series)

@app.route('/run-sync-movies', methods=['POST'])
def run_sync_movies_now():
    logger.info("Iniciando sincronización de películas...")
    run_sync_movies.delay()
    flash('Sincronización de películas iniciada!')
    return redirect(url_for('index'))

@app.route('/run-sync-series', methods=['POST'])
def run_sync_series_now():
    logger.info("Iniciando sincronización de series...")
    run_sync_series.delay()
    flash('Sincronización de series iniciada!')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
