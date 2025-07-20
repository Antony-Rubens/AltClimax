from openai import OpenAI
import os
from flask import Flask, request, jsonify, render_template, send_from_directory
from bs4 import BeautifulSoup
import google.generativeai as genai
import requests
from urllib.parse import quote
import re
import logging
import time
import sqlite3
import json
from datetime import datetime
import hashlib
from google.cloud import texttospeech
from google.oauth2 import service_account
from google.cloud.texttospeech import SsmlVoiceGender
import base64
from io import BytesIO
from PIL import Image
import subprocess

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# ========================
# CONFIGURATION
# ========================
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', 'AIzaSyDy3Cf96QgeW8eLFumryvR5q4dPzfjG4eY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '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')
genai.configure(api_key=GOOGLE_API_KEY)

# Supported voices
SUPPORTED_VOICES = {
    "en-US": [
        {"name": "en-US-Neural2-A", "gender": SsmlVoiceGender.FEMALE},
        {"name": "en-US-Neural2-C", "gender": SsmlVoiceGender.FEMALE},
        {"name": "en-US-Neural2-D", "gender": SsmlVoiceGender.MALE},
        {"name": "en-US-Neural2-E", "gender": SsmlVoiceGender.FEMALE},
        {"name": "en-US-Neural2-F", "gender": SsmlVoiceGender.FEMALE},
        {"name": "en-US-Neural2-G", "gender": SsmlVoiceGender.FEMALE},
        {"name": "en-US-Neural2-H", "gender": SsmlVoiceGender.FEMALE},
        {"name": "en-US-Neural2-I", "gender": SsmlVoiceGender.MALE},
        {"name": "en-US-Neural2-J", "gender": SsmlVoiceGender.MALE},
    ]
}

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ========================
# TEXT-TO-SPEECH SETUP
# ========================
def init_tts_client():
    try:
        if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
            return texttospeech.TextToSpeechClient()
        
        cred_path = os.path.join(os.path.dirname(__file__), 'service-account.json')
        if os.path.exists(cred_path):
            creds = service_account.Credentials.from_service_account_file(cred_path)
            return texttospeech.TextToSpeechClient(credentials=creds)
        
        return texttospeech.TextToSpeechClient()
    except Exception as e:
        app.logger.error(f"TTS Client initialization failed: {str(e)}")
        return None

tts_client = init_tts_client()

# ========================
# DATABASE SETUP
# ========================
def init_db():
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS script_cache
                 (movie TEXT PRIMARY KEY, script TEXT, timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ending_cache
                 (movie TEXT, prompt TEXT, result TEXT, timestamp TIMESTAMP,
                  PRIMARY KEY (movie, prompt))''')
    c.execute('''CREATE TABLE IF NOT EXISTS audio_cache
                 (dialogue_hash TEXT PRIMARY KEY, audio_path TEXT, timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS image_cache
                 (description_hash TEXT PRIMARY KEY, image_paths TEXT, timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS video_cache
                 (video_hash TEXT PRIMARY KEY, video_path TEXT, timestamp TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# ========================
# UTILITY FUNCTIONS
# ========================
def get_voice_gender(voice_name):
    for voice in SUPPORTED_VOICES["en-US"]:
        if voice["name"] == voice_name:
            return voice["gender"]
    return SsmlVoiceGender.MALE

def get_cached_ending(movie, prompt):
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute("SELECT result FROM ending_cache WHERE movie=? AND prompt=?", (movie, prompt))
    result = c.fetchone()
    conn.close()
    return json.loads(result[0]) if result else None

def cache_ending(movie, prompt, result):
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO ending_cache VALUES (?, ?, ?, ?)",
              (movie, prompt, json.dumps(result), datetime.now()))
    conn.commit()
    conn.close()

def get_movie_script(movie):
    base_url = "https://imsdb.com"
    search_paths = [
        f"/scripts/{quote(movie.replace(' ', '-'))}.html",
        f"/Movie%20Scripts/{quote(movie)}%20Script.html",
        f"/scripts/{quote(movie)}.html"
    ]

    for path in search_paths:
        try:
            response = requests.get(f"{base_url}{path}", timeout=10, 
                                  headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                script_text = soup.find("td", class_="scrtext")
                if script_text:
                    for elem in script_text(['pre', 'script', 'style']):
                        elem.decompose()
                    return script_text.get_text()
        except requests.RequestException as e:
            app.logger.error(f"Request error for {path}: {str(e)}")
            continue
    return None

def extract_component(text, component):
    try:
        pattern = rf"^{re.escape(component)}\s*:\s*(.*?)(?=\n\w+\s*:|$)"
        match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
        if match:
            return match.group(1).strip()
        
        pattern = rf"{re.escape(component)}\s*:\s*(.*?)(?=\n\|?$)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else f"Component {component} not found"
    except Exception as e:
        app.logger.error(f"Error extracting component {component}: {str(e)}")
        return f"Error extracting {component}"

def generate_with_retry(model, prompt, max_retries=3, retry_delay=5):
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt)
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "quota" in error_msg.lower():
                sleep_time = retry_delay * (2 ** attempt)
                app.logger.warning(f"Rate limited. Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                raise
    raise Exception("Max retries exceeded for Gemini API")

def get_audio_duration(audio_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return float(result.stdout.strip())
    except Exception as e:
        app.logger.error(f"Error getting audio duration: {str(e)}")
        return 5.0  # Default duration if we can't determine

# ========================
# ROUTES
# ========================
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
    script = get_movie_script(movie)
    return jsonify({"exists": bool(script)})

@app.route("/generate_script", methods=["POST"])
def generate_script():
    data = request.json
    movie = data.get("movie", "").strip()
    prompt = data.get("prompt", "").strip()

    if not all([movie, prompt]):
        return jsonify({"error": "Movie and prompt are required"}), 400

    cached_ending = get_cached_ending(movie, prompt)
    if cached_ending:
        return jsonify({
            "status": "success",
            "movie": movie,
            "alternate_ending": cached_ending.get("alternate_ending", ""),
            "visual_description": cached_ending.get("visual_description", ""),
            "narration_text": cached_ending.get("narration_text", ""),
            "character_dialogue": cached_ending.get("character_dialogue", ""),
            "production_notes": cached_ending.get("production_notes", "")
        })

    script = get_movie_script(movie)
    if not script:
        return jsonify({"error": "Failed to fetch script"}), 404

    try:
        context = script[:1500]
        full_prompt = f"""Create a generic alternate ending inspired by stories similar to "{movie}" based on:
{prompt}

Original context (partial):
{context}

Important Guidelines:
1. Replace specific character names with generic descriptions (e.g., "the brave captain" instead of "Jack Dawson")
2. Avoid mentioning or generating images which has copyrighted elements like actor names, exact locations, or trademarked items
3. Keep the essence of the story while making it original

Respond EXACTLY in this format without any additional commentary:

=== Alternate Ending ===
Visual: [Generic scene description using character types not names]
Narration: [Narration text about character types]
Dialogue: [Generic character lines without proper names]
Notes: [Production details using generic terms]"""
        
        model = genai.GenerativeModel("gemini-2.5-pro")
        response = generate_with_retry(model, full_prompt)
        ending_text = response.text.strip()
        
        if "=== Alternate Ending ===" in ending_text:
            ending_text = ending_text.split("=== Alternate Ending ===")[1].strip()
        
        result = {
            "movie": movie,
            "alternate_ending": ending_text,
            "visual_description": extract_component(ending_text, "Visual"),
            "narration_text": extract_component(ending_text, "Narration"),
            "character_dialogue": extract_component(ending_text, "Dialogue"),
            "production_notes": extract_component(ending_text, "Notes")
        }
        
        cache_ending(movie, prompt, result)
        return jsonify({"status": "success", **result})
        
    except Exception as e:
        app.logger.error(f"Generation failed: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Generation failed. Please try a different movie or prompt.",
            "error": str(e)
        }), 500

@app.route("/generate_audio", methods=["POST"])
def generate_audio():
    if tts_client is None:
        return jsonify({
            "status": "error",
            "message": "Text-to-Speech service unavailable",
            "error": "TTS client not initialized"
        }), 503

    data = request.json
    text = data.get("text", "").strip()
    voice_name = data.get("voice", "en-US-Neural2-J")
    
    if not text:
        return jsonify({"error": "Text is required for audio generation"}), 400
    
    if len(text) > 5000:
        return jsonify({"error": "Text too long (max 5000 characters)"}), 400
        
    try:
        text_hash = hashlib.md5((text + voice_name).encode()).hexdigest()
        audio_dir = os.path.join('static', 'audio')
        os.makedirs(audio_dir, exist_ok=True)
        audio_path = os.path.join(audio_dir, f"{text_hash}.mp3")
        
        if os.path.exists(audio_path):
            return jsonify({
                "status": "success", 
                "audio_url": f"/static/audio/{text_hash}.mp3",
                "audio_path": audio_path
            })
        
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=voice_name,
            ssml_gender=get_voice_gender(voice_name)
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
            pitch=0,
            volume_gain_db=0
        )

        response = tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        with open(audio_path, "wb") as out:
            out.write(response.audio_content)
        
        return jsonify({
            "status": "success", 
            "audio_url": f"/static/audio/{text_hash}.mp3",
            "audio_path": audio_path
        })
    except Exception as e:
        app.logger.error(f"Audio generation failed: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Audio generation failed",
            "error": str(e)
        }), 500

@app.route("/generate_images", methods=["POST"])
def generate_images():
    data = request.json
    description = data.get("description", "").strip()
    num_images = min(int(data.get("num_images", 3)), 5)  # Max 5 images
    
    if not description:
        return jsonify({"error": "Description is required"}), 400
    
    try:
        # Check cache first
        desc_hash = hashlib.md5((description + str(num_images)).encode()).hexdigest()
        conn = sqlite3.connect('cache.db')
        c = conn.cursor()
        c.execute("SELECT image_paths FROM image_cache WHERE description_hash=?", (desc_hash,))
        cached = c.fetchone()
        
        if cached:
            conn.close()
            return jsonify({
                "status": "success",
                "image_urls": json.loads(cached[0])
            })
        
        # Generate new images using DALL-E 3
        app.logger.info(f"Generating {num_images} images with DALL-E 3 for: {description[:100]}...")
        
        image_urls = []
        img_dir = os.path.join('static', 'images')
        os.makedirs(img_dir, exist_ok=True)
        
        for i in range(num_images):
            response = openai_client.images.generate(
                model="dall-e-3",
                prompt=f"{description} (variation {i+1})",
                size="1024x1024",
                quality="standard",
                n=1
            )
            
            # Download and save the image
            image_url = response.data[0].url
            img_response = requests.get(image_url)
            img_response.raise_for_status()
            
            img_path = os.path.join(img_dir, f"{desc_hash}_{i}.png")
            
            with open(img_path, "wb") as f:
                f.write(img_response.content)
            
            image_urls.append(f"/static/images/{desc_hash}_{i}.png")
        
        # Cache the result
        c.execute("INSERT OR REPLACE INTO image_cache VALUES (?, ?, ?)",
                 (desc_hash, json.dumps(image_urls), datetime.now()))
        conn.commit()
        conn.close()
        
        return jsonify({
            "status": "success",
            "image_urls": image_urls
        })
        
    except Exception as e:
        app.logger.error(f"Image generation failed: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Image generation failed",
            "error": str(e)
        }), 500

@app.route("/create_video", methods=["POST"])
def create_video():
    data = request.json
    image_urls = data.get("image_urls", [])
    audio_url = data.get("audio_url", "")
    
    if not image_urls or not audio_url:
        return jsonify({"error": "Both images and audio are required"}), 400
    
    try:
        # Create unique ID for this video
        video_hash = hashlib.md5((str(image_urls) + audio_url).encode()).hexdigest()
        output_path = os.path.join('static', 'videos', f"{video_hash}.mp4")
        
        # Check if video already exists
        conn = sqlite3.connect('cache.db')
        c = conn.cursor()
        c.execute("SELECT video_path FROM video_cache WHERE video_hash=?", (video_hash,))
        cached = c.fetchone()
        
        if cached:
            conn.close()
            return jsonify({
                "status": "success",
                "video_url": cached[0]
            })
        
        # Get audio file path and duration
        audio_path = os.path.join('static', audio_url.lstrip('/static/'))
        if not os.path.exists(audio_path):
            return jsonify({"error": "Audio file not found"}), 404
        
        audio_duration = get_audio_duration(audio_path)
        per_image_duration = audio_duration / len(image_urls)
        
        # Prepare FFmpeg command
        ffmpeg_cmd = [
            'ffmpeg',
            '-y',  # Overwrite output file without asking
        ]
        
        # Add input images
        for img_url in image_urls:
            img_path = os.path.join('static', img_url.lstrip('/static/'))
            ffmpeg_cmd.extend([
                '-loop', '1',
                '-t', str(per_image_duration),
                '-i', img_path
            ])
        
        # Add audio input
        ffmpeg_cmd.extend([
            '-i', audio_path,
            '-filter_complex',
            f'concat=n={len(image_urls)}:v=1:a=0[v]',
            '-map', '[v]',
            '-map', f'{len(image_urls)}:a',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-vf', 'scale=1920:1080',
            '-c:a', 'aac',
            '-shortest',
            output_path
        ])
        
        # Run FFmpeg
        subprocess.run(ffmpeg_cmd, check=True)
        
        # Cache the result
        video_url = f"/static/videos/{video_hash}.mp4"
        c.execute("INSERT OR REPLACE INTO video_cache VALUES (?, ?, ?)",
                 (video_hash, video_url, datetime.now()))
        conn.commit()
        conn.close()
        
        return jsonify({
            "status": "success",
            "video_url": video_url
        })
        
    except subprocess.CalledProcessError as e:
        app.logger.error(f"FFmpeg failed: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Video creation failed",
            "error": str(e)
        }), 500
    except Exception as e:
        app.logger.error(f"Video creation failed: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Video creation failed",
            "error": str(e)
        }), 500

@app.route("/health")
def health_check():
    try:
        tts_status = False
        if tts_client:
            try:
                tts_client.list_voices()
                tts_status = True
            except:
                tts_status = False
        
        # Check OpenAI connection
        openai_status = False
        try:
            openai_client.models.list()
            openai_status = True
        except:
            openai_status = False
        
        # Check FFmpeg availability
        ffmpeg_status = False
        try:
            subprocess.run(['ffmpeg', '-version'], check=True, 
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            ffmpeg_status = True
        except:
            ffmpeg_status = False
        
        return jsonify({
            "status": "healthy" if all([tts_status, openai_status, ffmpeg_status]) else "degraded",
            "services": {
                "text_to_speech": tts_status,
                "database": True,
                "gemini_api": True,
                "openai_api": openai_status,
                "ffmpeg": ffmpeg_status
            }
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

if __name__ == "__main__":
    # Create required directories
    os.makedirs("static/audio", exist_ok=True)
    os.makedirs("static/images", exist_ok=True)
    os.makedirs("static/videos", exist_ok=True)
    
    app.run(debug=True, port=5000)