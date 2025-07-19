from flask import Flask, request, jsonify, render_template, send_from_directory
from bs4 import BeautifulSoup
import google.generativeai as genai
import requests
from urllib.parse import quote
import os
import re
import logging
import time
import sqlite3
import json
from datetime import datetime

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# Configure Gemini - with fallback model
GOOGLE_API_KEY = "AIzaSyDy3Cf96QgeW8eLFumryvR5q4dPzfjG4eY"
genai.configure(api_key=GOOGLE_API_KEY)

# Use the free tier model with higher quotas
model = genai.GenerativeModel('gemini-2.5-pro')

# Setup caching database
def init_db():
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS script_cache
                 (movie TEXT PRIMARY KEY, script TEXT, timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ending_cache
                 (movie TEXT, prompt TEXT, result TEXT, timestamp TIMESTAMP,
                  PRIMARY KEY (movie, prompt))''')
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    return render_template("index.html")

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

@app.route("/check_movie", methods=["POST"])
def check_movie():
    movie = request.json.get("movie", "").strip()
    if not movie:
        return jsonify({"error": "Movie name is required"}), 400

    # Try multiple URL patterns
    base_url = "https://imsdb.com"
    search_paths = [
        f"/scripts/{quote(movie.replace(' ', '-'))}.html",
        f"/Movie%20Scripts/{quote(movie)}%20Script.html",
        f"/scripts/{quote(movie)}.html"
    ]

    for path in search_paths:
        try:
            response = requests.get(f"{base_url}{path}", timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                if soup.find("td", class_="scrtext"):
                    return jsonify({"exists": True, "movie": movie})
        except requests.RequestException as e:
            app.logger.error(f"Request error for {path}: {str(e)}")
            continue

    return jsonify({"exists": False, "error": "Movie not found on IMSDB"}), 404

@app.route("/generate_ending", methods=["POST"])
def generate_ending():
    data = request.json
    movie = data.get("movie", "").strip()
    prompt = data.get("prompt", "").strip()

    if not all([movie, prompt]):
        return jsonify({"error": "Movie and prompt are required"}), 400

    # Check cache first
    cached_ending = get_cached_ending(movie, prompt)
    if cached_ending:
        return jsonify(cached_ending)

    # Get script from IMSDB
    script = get_movie_script(movie)
    if not script:
        return jsonify({"error": "Failed to fetch script"}), 404

    # Generate alternate ending with retry logic
    max_retries = 3
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            # Use a smaller context to reduce token usage
            context = script[:3000]  # Reduced from 8000 to 3000
            
            # Optimized prompt for token efficiency
            full_prompt = f"""Create an alternate ending for "{movie}" based on:
{prompt}

Original context (partial):
{context}

Format:
=== Alternate Ending ===
*Visual*: [Scene description]
*Narration*: [Narration text]
*Dialogue*: [Character lines]
*Notes*: [Production details]"""
            
            response = model.generate_content(full_prompt)
            ending_text = response.text
            
            # Extract components
            visual_description = extract_component(ending_text, "Visual")
            narration_text = extract_component(ending_text, "Narration")
            character_dialogue = extract_component(ending_text, "Dialogue")
            production_notes = extract_component(ending_text, "Notes")
            
            result = {
                "status": "success",
                "movie": movie,
                "alternate_ending": ending_text,
                "visual_description": visual_description,
                "narration_text": narration_text,
                "character_dialogue": character_dialogue,
                "production_notes": production_notes
            }
            
            # Cache the result
            cache_ending(movie, prompt, result)
            
            return jsonify(result)
            
        except Exception as e:
            error_msg = str(e)
            app.logger.error(f"Attempt {attempt+1} failed: {error_msg}")
            
            if "429" in error_msg or "quota" in error_msg.lower():
                # Exponential backoff for rate limits
                sleep_time = retry_delay * (2 ** attempt)
                app.logger.info(f"Rate limited. Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                return jsonify({"error": f"Generation failed: {error_msg}"}), 500
    
    return jsonify({"error": "Generation failed after multiple attempts. Please try again later."}), 500

def get_movie_script(movie_name):
    # Check cache first
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute("SELECT script FROM script_cache WHERE movie = ?", (movie_name,))
    row = c.fetchone()
    if row:
        conn.close()
        return row[0]
    
    base_url = "https://imsdb.com"
    search_paths = [
        f"/scripts/{quote(movie_name.replace(' ', '-'))}.html",
        f"/Movie%20Scripts/{quote(movie_name)}%20Script.html",
        f"/scripts/{quote(movie_name)}.html"
    ]
    
    for path in search_paths:
        try:
            response = requests.get(f"{base_url}{path}", timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                script_tag = soup.find("td", class_="scrtext")
                if script_tag:
                    script = script_tag.get_text(separator="\n", strip=True)
                    # Cache the script
                    c.execute("INSERT OR REPLACE INTO script_cache (movie, script, timestamp) VALUES (?, ?, ?)",
                              (movie_name, script, datetime.now()))
                    conn.commit()
                    conn.close()
                    return script
        except requests.RequestException:
            continue
    
    conn.close()
    return None

def extract_component(text, component_name):
    pattern = rf"\*{component_name}\*\s*:\s*(.*?)(?=\*[^:]+:|$)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else f"Component '{component_name}' not found"

def cache_ending(movie, prompt, result):
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO ending_cache (movie, prompt, result, timestamp) VALUES (?, ?, ?, ?)",
              (movie, prompt, json.dumps(result), datetime.now()))
    conn.commit()
    conn.close()

def get_cached_ending(movie, prompt):
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute("SELECT result FROM ending_cache WHERE movie = ? AND prompt = ?", (movie, prompt))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

if __name__ == "__main__":
    app.run(debug=True, port=5000)