📌 Basic Details
Team Name: DEVEMPHASIS

Team Members: Antony Rubens,Alan Verghese Mathew,Mohammed Zayan,Haebel Ebby Chirayil 

Hackathon Track:Generative AI Hackathon for entertainment

Problem Statement:
Can we reimagine movie scenes by emotionally rewriting the climax or transforming the scene's mood using Generative AI, enhancing storytelling and accessibility for an unsatissfied movie ending giving a creative tool to the user/audience.

Solution:
An AI system that takes in movie scripts, detects a target scene, analyzes the emotion, and regenerates the climax or context (e.g., changing a sad ending to a happy one) using AI api 's other AI tools

Project Description:
Our project allows users to select a  movie and then it calls and goes into the url of imsdb and this is where the python library beautifullsoup scrapes data from imsdb to get the whole script structure.Then we take in the Gemini 2.5 pro api keys and asks it to analyze the script and then it breaks down into summary,characters and makes it easier to find a scene that doesn't suite their taste and then Gemini AI api does the  Google TTS for voice generation,  DALL·E FOR IMAGE PROCESSING and changing their framerates to make it into a slideshow with voice and image in sync to bring in a smooth flow of presentation and better entertainmental view for audience  . The idea is to reimagine narratives, support creators, and even make content more accessible or culturally adaptive.

🧑‍💻 Technical Details
Tech Stack:

Frontend: HTML, CSS, JS

Backend: Python + Flask

APIs Used:

Gemini Pro 2.5 (Google Generative AI) – for script rewriting

GOOGLE TTS- for voice cloning / TTS

DALL·E (OpenAI) – for visual generation

IMSDb Scraper – to fetch movie scripts

Libraries Used:

Flask, Requests, BeautifulSoup, google.generativeai, openai,etc 






🚀 Installation & Execution
Clone the repository

bash
Copy
Edit
git clone https://github.com/Antony-Rubens/AltClimax/tree/Final-product-submitted-for-hackathon
cd alt-climax-ai
Set up a virtual environment

bash
Copy
Edit
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
Install dependencies

bash
Copy
Edit
pip install -r requirements.txt
Set up API keys


Create a .env file and add:
env
Copy
Edit
GOOGLE_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_key  # Optional for DALL·E
Run the Flask app

bash
Copy
Edit
python app.py


Access the web interface


