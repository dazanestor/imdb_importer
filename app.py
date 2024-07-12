from flask import Flask, render_template, request, redirect, url_for, flash
import json
from tasks import run_sync_movies, run_sync_series

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Leer configuración desde un archivo JSON
def read_config():
    with open('config.json', 'r') as f:
        return json.load(f)

# Guardar configuración en un archivo JSON
def write_config(data):
    with open('config.json', 'w') as f:
        json.dump(data, f, indent=4)

@app.route('/', methods=['GET', 'POST'])
def index():
    config = read_config()
    if request.method == 'POST':
        config['imdb_list_url'] = request.form['imdb_list_url']
        config['radarr_api_key'] = request.form['radarr_api_key']
        config['sonarr_api_key'] = request.form['sonarr_api_key']
        config['movies_min_year'] = int(request.form['movies_min_year'])
        config['movies_max_year'] = int(request.form['movies_max_year'])
        config['movies_min_rating'] = float(request.form['movies_min_rating'])
        config['series_min_year'] = int(request.form['series_min_year'])
        config['series_max_year'] = int(request.form['series_max_year'])
        config['series_min_rating'] = float(request.form['series_min_rating'])
        write_config(config)
        flash('Configuración guardada exitosamente!')
        return redirect(url_for('index'))
    return render_template('index.html', config=config)

@app.route('/run-sync-movies', methods=['POST'])
def run_sync_movies_now():
    run_sync_movies.delay()
    flash('Sincronización de películas iniciada!')
    return redirect(url_for('index'))

@app.route('/run-sync-series', methods=['POST'])
def run_sync_series_now():
    run_sync_series.delay()
    flash('Sincronización de series iniciada!')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
