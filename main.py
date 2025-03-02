import os
import re
import logging
import time
import threading
import shutil
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
import zipfile
import requests
import subprocess
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from jinja2 import DictLoader

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spotify_downloader")

# Define FFmpeg binary path from the "ast" folder (adjust for Windows as needed)
FFMPEG_BIN = os.path.join(os.getcwd(), "ast", "ffmpeg.exe")
# Default thumbnail fallback from main directory
DEFAULT_THUMB = os.path.join(os.getcwd(), "d.png")

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Define custom CSS style (no Bootstrap)
custom_css = """
<style>
    html {
        background:black;
    }
  body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      background: black;
      color:white;
      margin: 0;
      padding: 0;
      height:100%;
      width:100%;
  }
  .navbar {
      background-color: black;
      color: #fff;
      padding: 15px;
      text-align: center;
  }
  .navbar h1 {
      margin: 0;
      font-size: 24px;
  }
  .container {
      width: 90%;
      max-width: 800px;
      margin: 30px auto;
      background-color: black;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
      padding: 20px;
      border-radius: 8px;
  }
  h2 {
      color: white;
      text-align: center;
      margin-bottom: 20px;
  }
  form {
    display:flex;
    flex-direction:column;
  }
  form label {
      font-weight: bold;
      display: block;
      margin-bottom: 5px;
  }
  form input[type="text"], form select {
      padding: 10px;
      border: 1px solid #ccc;
      border-radius: 4px;
      margin-bottom: 15px;
      background:black;
      color:white;
  }
  form button {
      background-color: black;
      color: white;
      outline:1px solid white;
      border: none;
      padding: 8px 15px;
      border-radius: 4px;
      cursor: pointer;
  }
  form button:hover {
      background-color: #0056b3;
  }
  .alert {
      padding: 10px 15px;
      margin-bottom: 20px;
      border-radius: 4px;
  }
  .alert-info {
      background-color: black;
      color: white;
  }
  .alert-success {
      background-color: black;
      color: white;
  }
  .alert-danger {
      background-color: black;
      color: red;
  }
  a {
      color: #007bff;
      text-decoration: none;
  }
  a:hover {
      text-decoration: underline;
  }
  .btn-secondary {
      background-color: black;
      color: white;
      outline:1px solid white;
      border: none;
      padding: 8px 15px;
      border-radius: 4px;
      cursor: pointer;
  }
  .btn-secondary:hover {
      background-color: #5a6268;
  }
</style>
"""

# Define HTML templates using custom CSS
base_template = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SilverSniper-SpotifyDownloader</title>
    {custom_css}
  </head>
  <body>
    <div class="navbar">
      <h1>SilverSniper-SpotifyDownloader</h1>
    </div>
    <div class="container">
      {{% with messages = get_flashed_messages() %}}
        {{% if messages %}}
          <div class="alert alert-info">
            {{% for message in messages %}}
              <div>{{{{ message }}}}</div>
            {{% endfor %}}
          </div>
        {{% endif %}}
      {{% endwith %}}
      {{% block content %}}{{% endblock %}}
    </div>
  </body>
</html>
"""

home_template = """
{% extends "base.html" %}
{% block content %}
  <h2>Enter Spotify URL</h2>
  <form method="post" action="{{ url_for('download') }}">
    <label for="spotify_url">Spotify URL (track, album, or playlist):</label>
    <input type="text" id="spotify_url" name="spotify_url" placeholder="https://open.spotify.com/track/..." required>

    <label for="sound_quality">Sound Quality (kbps):</label>
    <select id="sound_quality" name="sound_quality">
      <option value="64">64</option>
      <option value="128">128</option>
      <option value="192" selected>192</option>
      <option value="320">320</option>
    </select>

    <!-- Dropdown for metadata options -->
    <label for="metadata_options">Metadata Options:</label>
    <select id="metadata_options" name="metadata_options">
      <option value="all" selected>All (Title, Artist, Album, Date, Track Number, Disc Number, Thumbnail)</option>
      <option value="basic">Basic (Title, Artist)</option>
      <option value="minimal">Minimal (Title only)</option>
      <option value="none">None</option>
    </select>

    <label for="playlist_order">Playlist Order:</label>
    <select id="playlist_order" name="playlist_order">
      <option value="as_is" selected>As Is</option>
      <option value="reverse">Reverse</option>
    </select>

    <button type="submit">Download</button>
  </form>
{% endblock %}
"""

result_template = """
{% extends "base.html" %}
{% block content %}
  <h2>Download Results</h2>
  {% if error %}
    <div class="alert alert-danger">{{ error }}</div>
  {% else %}
    {% if zip_file %}
      <div class="alert alert-success">Successfully created ZIP archive:</div>
      <ul>
        <li><a href="{{ url_for('downloaded_file', filename=zip_file) }}">{{ zip_file }}</a></li>
      </ul>
    {% else %}
      <div class="alert alert-success">Successfully downloaded the file:</div>
      <ul>
        {% for file in files %}
          <li><a href="{{ url_for('downloaded_file', filename=file) }}">{{ file }}</a></li>
        {% endfor %}
      </ul>
    {% endif %}
  {% endif %}
  <a class="btn-secondary" href="{{ url_for('home') }}">Back</a>
{% endblock %}
"""

# Set up a Jinja2 DictLoader with our templates
app.jinja_loader = DictLoader({
    "base.html": base_template,
    "home.html": home_template,
    "result.html": result_template,
})

def get_items_from_spotify(sp, url_type, spotify_id):
    if url_type == "track":
        track = sp.track(spotify_id)
        return [track], track.get("name", "Track")
    elif url_type == "album":
        album = sp.album(spotify_id)
        # Fetch album tracks (handle pagination if needed)
        tracks = album.get("tracks", {}).get("items", [])
        return tracks, album.get("name", "Album")
    elif url_type == "playlist":
        playlist = sp.playlist(spotify_id)
        # Playlist items usually wrap the track info inside a "track" key.
        tracks = [item["track"] for item in playlist.get("tracks", {}).get("items", []) if item.get("track")]
        return tracks, playlist.get("name", "Playlist")
    else:
        raise ValueError("Invalid Spotify URL type.")

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/download", methods=["POST"])
def download():
    spotify_url = request.form.get("spotify_url", "").strip()
    if not spotify_url:
        flash("Please provide a Spotify URL.")
        return redirect(url_for("home"))
    
    url_type, spotify_id = extract_spotify_id(spotify_url)
    if not url_type or not spotify_id:
        error = "Invalid Spotify URL."
        return render_template("result.html", error=error, files=None, zip_file=None)
    
    # Retrieve extra options from the form
    sound_quality = request.form.get("sound_quality", "192")
    playlist_order = request.form.get("playlist_order", "as_is")
    
    # Retrieve metadata options from dropdown and set flags accordingly:
    metadata_option = request.form.get("metadata_options", "all")
    if metadata_option == "all":
        include_title = include_artist = include_album = include_date = include_track = include_disc = include_thumbnail = True
    elif metadata_option == "basic":
        include_title = include_artist = True
        include_album = include_date = include_track = include_disc = include_thumbnail = False
    elif metadata_option == "minimal":
        include_title = True
        include_artist = include_album = include_date = include_track = include_disc = include_thumbnail = False
    elif metadata_option == "none":
        include_title = include_artist = include_album = include_date = include_track = include_disc = include_thumbnail = False
    else:
        include_title = include_artist = include_album = include_date = include_track = include_disc = include_thumbnail = True




#Paste your id and that here






#------------------------------------



    client_id = ""
    client_secret = ""




#-------------------------------------












    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id,
                                                               client_secret=client_secret))
    try:
        items, collection_name = get_items_from_spotify(sp, url_type, spotify_id)
        # If user selects reverse order, reverse the items list
        if url_type == "playlist" and playlist_order == "reverse":
            items.reverse()
    except Exception as e:
        error = f"Failed to fetch items: {e}"
        return render_template("result.html", error=error, files=None, zip_file=None)
    
    downloads_dir = os.path.join(os.getcwd(), "downloads")
    os.makedirs(downloads_dir, exist_ok=True)
    
    # For single track downloads
    if url_type == "track" or len(items) == 1:
        track = items[0]
        query = build_query(track)
        logger.info(f"Search query: {query}")
        artist = ", ".join([a["name"] for a in track.get("artists", [])])
        title = track.get("name", "")
        base_filename = sanitize_filename(f"{artist} - {title}")
        output_path = None
        for attempt in range(3):
            output_path = download_song(query, downloads_dir, base_filename, ffmpeg_path=FFMPEG_BIN, sound_quality=sound_quality)
            if output_path:
                try:
                    embed_metadata_ffmpeg(output_path, track, ffmpeg_bin=FFMPEG_BIN,
                                            include_title=include_title,
                                            include_artist=include_artist,
                                            include_album=include_album,
                                            include_date=include_date,
                                            include_track=include_track,
                                            include_disc=include_disc,
                                            include_thumbnail=include_thumbnail)
                    break
                except Exception as e:
                    logger.error(f"Embedding metadata failed on attempt {attempt+1}: {e}")
                    output_path = None
            time.sleep(1)
        if output_path:
            files = [os.path.basename(output_path)]
            return render_template("result.html", files=files, error=None, zip_file=None)
        else:
            error = "Failed to download the song after multiple attempts."
            return render_template("result.html", error=error, files=None, zip_file=None)
    else:
        # For album or playlist downloads (sequential processing)
        collection_folder = os.path.join(downloads_dir, sanitize_filename(collection_name))
        os.makedirs(collection_folder, exist_ok=True)
        logger.info(f"Downloading {len(items)} tracks into folder '{collection_folder}'")
        
        def process_track(track):
            output = None
            for attempt in range(3):
                q = build_query(track)
                artist = ", ".join([a["name"] for a in track.get("artists", [])])
                title = track.get("name", "")
                base_fn = sanitize_filename(f"{artist} - {title}")
                logger.info(f"Downloading track: {base_fn}")
                output = download_song(q, collection_folder, base_fn, ffmpeg_path=FFMPEG_BIN, sound_quality=sound_quality)
                if output:
                    try:
                        embed_metadata_ffmpeg(output, track, ffmpeg_bin=FFMPEG_BIN,
                                                include_title=include_title,
                                                include_artist=include_artist,
                                                include_album=include_album,
                                                include_date=include_date,
                                                include_track=include_track,
                                                include_disc=include_disc,
                                                include_thumbnail=include_thumbnail)
                        break
                    except Exception as e:
                        logger.error(f"Embedding metadata for '{base_fn}' failed on attempt {attempt+1}: {e}")
                        output = None
                time.sleep(1)
            return output
        
        # Process each track sequentially
        for track in items:
            process_track(track)
        
        # At final encoding, rename files based on order from Spotify data.
        # Use the current order of the 'items' list (which may be reversed if selected).
        for idx, track in enumerate(items, start=1):
            artist = ", ".join([a["name"] for a in track.get("artists", [])])
            title = track.get("name", "")
            base_fn = sanitize_filename(f"{artist} - {title}")
            original_path = os.path.join(collection_folder, f"{base_fn}.mp3")
            if os.path.exists(original_path):
                new_path = os.path.join(collection_folder, f"{idx:02d} - {base_fn}.mp3")
                try:
                    os.rename(original_path, new_path)
                except Exception as e:
                    logger.error(f"Error renaming file {original_path} to {new_path}: {e}")
        
        zip_file_name = sanitize_filename(collection_name) + ".zip"
        zip_file_path = os.path.join(downloads_dir, zip_file_name)
        zip_folder(collection_folder, zip_file_path)
        logger.info(f"Created ZIP file: {zip_file_path}")
        return render_template("result.html", files=None, error=None, zip_file=zip_file_name)

@app.route("/downloads/<path:filename>")
def downloaded_file(filename):
    downloads_dir = os.path.join(os.getcwd(), "downloads")
    return send_from_directory(downloads_dir, filename)

def zip_folder(source_dir, zip_file_path):
    """Zip the contents of source_dir into a zip file at zip_file_path."""
    with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)

# Updated download_song accepts a new parameter 'sound_quality'
def download_song(query, downloads_dir, base_filename, ffmpeg_path=FFMPEG_BIN, sound_quality="192"):
    output_template = os.path.join(downloads_dir, f"{base_filename}.%(ext)s")
    final_filename = f"{base_filename}.mp3"
    final_path = os.path.join(downloads_dir, final_filename)
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "ffmpeg_location": ffmpeg_path,
        "retries": 3,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": sound_quality
        }],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info("ytsearch:" + query, download=False)
            if "entries" in info and len(info["entries"]) > 0:
                video = info["entries"][0]
                video_url = video.get("webpage_url")
                logger.info(f"Found video: {video_url}")
                ydl.download([video_url])
                if os.path.exists(final_path):
                    return final_path
    except Exception as e:
        logger.error(f"Error downloading song: {e}")
    return None

def embed_metadata_ffmpeg(file_path, track, ffmpeg_bin=FFMPEG_BIN, attempts=3,
                          include_title=True, include_artist=True, include_album=True,
                          include_date=True, include_track=True, include_disc=True,
                          include_thumbnail=True):
    """
    Re-invokes FFmpeg to embed metadata (title, artist, album, date, track, disc, and cover image)
    into the MP3 file. Retries up to 'attempts' times.
    If album art download fails, falls back to default thumbnail "d.png".
    """
    for attempt in range(attempts):
        try:
            metadata_opts = []
            if include_title:
                t = track.get("name", "")
                if t:
                    metadata_opts.extend(["-metadata", f"title={t}"])
            if include_artist:
                artists = ", ".join([a["name"] for a in track.get("artists", [])])
                if artists:
                    metadata_opts.extend(["-metadata", f"artist={artists}"])
            if include_album and "album" in track:
                album_name = track["album"].get("name", "")
                if album_name:
                    metadata_opts.extend(["-metadata", f"album={album_name}"])
                if include_date:
                    release_date = track["album"].get("release_date", "")
                    if release_date:
                        metadata_opts.extend(["-metadata", f"date={release_date}"])
            if include_track and "track_number" in track:
                metadata_opts.extend(["-metadata", f"track={track.get('track_number', '')}"])
            if include_disc and "disc_number" in track:
                metadata_opts.extend(["-metadata", f"disc={track.get('disc_number', '')}"])
            
            album_art_path = None
            if include_thumbnail:
                if "album" in track and track["album"].get("images"):
                    image_url = track["album"]["images"][0]["url"]
                    try:
                        response = requests.get(image_url)
                        if response.status_code == 200:
                            album_art_path = os.path.join(os.path.dirname(file_path), "cover.jpg")
                            with open(album_art_path, "wb") as f:
                                f.write(response.content)
                        else:
                            raise Exception("Non-200 response")
                    except Exception as e:
                        logger.error(f"Error downloading album art: {e}")
                if album_art_path is None or not os.path.exists(album_art_path):
                    if os.path.exists(DEFAULT_THUMB):
                        album_art_path = DEFAULT_THUMB
                        logger.info("Using default thumbnail.")
                    else:
                        logger.warning("No album art available and default thumbnail not found.")
                        album_art_path = None
            
            temp_output = file_path + ".temp.mp3"
            if album_art_path:
                cmd = [ffmpeg_bin, "-y", "-i", file_path, "-i", album_art_path, "-map", "0:0", "-map", "1:0",
                       "-c", "copy", "-id3v2_version", "3"] + metadata_opts + [temp_output]
            else:
                cmd = [ffmpeg_bin, "-y", "-i", file_path, "-c", "copy", "-id3v2_version", "3"] + metadata_opts + [temp_output]
            
            logger.info("Running FFmpeg for metadata embedding: " + " ".join(cmd))
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode == 0:
                os.replace(temp_output, file_path)
                if album_art_path and album_art_path != DEFAULT_THUMB and os.path.exists(album_art_path):
                    time.sleep(1)
                    try:
                        os.remove(album_art_path)
                    except Exception as e:
                        logger.warning(f"Could not remove album art file: {e}")
                return
            else:
                logger.error("FFmpeg metadata embedding failed: " + result.stderr.decode("utf-8"))
        except Exception as e:
            logger.error(f"Attempt {attempt+1} embedding metadata failed: {e}")
        time.sleep(1)
    raise Exception("FFmpeg metadata embedding failed after multiple attempts.")

def extract_spotify_id(url):
    regex = r"open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)"
    match = re.search(regex, url)
    if match:
        return match.group(1), match.group(2)
    return None, None

def build_query(track):
    artist = ", ".join([a["name"] for a in track.get("artists", [])])
    title = track.get("name", "")
    return f"{artist} - {title} official audio"

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

# -------------------------------
# Cleanup functions for downloads folder
# -------------------------------
def cleanup_downloads():
    downloads_dir = os.path.join(os.getcwd(), "downloads")
    if os.path.exists(downloads_dir):
        for filename in os.listdir(downloads_dir):
            file_path = os.path.join(downloads_dir, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logger.error(f"Failed to delete {file_path}. Reason: {e}")

def periodic_cleanup():
    while True:
        time.sleep(15 * 60)  # 15 minutes
        cleanup_downloads()
        logger.info("Periodic cleanup of downloads folder completed.")

# Run cleanup on startup and start the periodic cleanup thread
cleanup_downloads()
threading.Thread(target=periodic_cleanup, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
