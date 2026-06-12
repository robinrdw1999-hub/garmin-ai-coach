import os
import json
import time
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from garminconnect import Garmin
import google.generativeai as genai

# Config
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_WACHTWOORD = os.environ.get("GARMIN_WACHTWOORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GMAIL_ADRES = os.environ.get("GMAIL_ADRES")
GMAIL_APP_WACHTWOORD = os.environ.get("GMAIL_APP_WACHTWOORD")
EMAIL_ONTVANGER = os.environ.get("EMAIL_ONTVANGER")
EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME")
GEKOZEN_INPUT = os.environ.get("CHOSEN_MODUS")

MODUS = "auto_coach" if EVENT_NAME == "schedule" else GEKOZEN_INPUT

try:
    print("Inloggen bij Garmin...")
    token_dir = os.path.expanduser("~/.garminconnect")
    os.makedirs(token_dir, exist_ok=True)
    
    garmin = Garmin(GARMIN_EMAIL, GARMIN_WACHTWOORD)
    garmin.login(token_dir)
    
    print("Activiteiten ophalen...")
    alle_activiteiten = garmin.get_activities(0, 10)
    if not alle_activiteiten:
        print("Geen activiteiten gevonden.")
        sys.exit(0)
    
    nieuwste_act = alle_activiteiten[0]
    nieuwste_id = nieuwste_act.get("activityId")
    start_time_str = nieuwste_act.get("startTimeLocal")
    nu_be = datetime.utcnow() + timedelta(hours=2)
    
    # Statuschecks
    last_id_file = os.path.join(token_dir, "last_activity_id.txt")
    if MODUS == "auto_coach":
        if os.path.exists(last_id_file):
            with open(last_id_file, "r") as f:
                if str(f.read().strip()) == str(nieuwste_id):
                    print("Activiteit al behandeld.")
                    sys.exit(0)
    
    # Data voorbereiden
    geschiedenis = [{
        "Naam": a.get("activityName"),
        "Datum": a.get("startTimeLocal"),
        "Afstand": a.get("distance"),
        "Duur": a.get("duration"),
        "HR": a.get("averageHR")
    } for a in alle_activiteiten]

    dagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    vandaag_voluit = f"{dagen[nu_be.weekday()]} {nu_be.day} juni 2026"

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"Je bent een wielercoach. Vandaag is {vandaag_voluit}. Analyseer deze data: {json.dumps(geschiedenis)}"
    
    print("Analyseer met Gemini...")
    response = model.generate_content(prompt)

    print("Mail verzenden...")
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = GMAIL_ADRES, EMAIL_ONTVANGER, "🚀 AI Coach Update"
    msg.attach(MIMEText(response.text, 'plain'))

    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(GMAIL_ADRES, GMAIL_APP_WACHTWOORD)
        server.sendmail(GMAIL_ADRES, EMAIL_ONTVANGER, msg.as_string())
    
    if MODUS == "auto_coach":
        with open(last_id_file, "w") as f: f.write(str(nieuwste_id))
    print("Klaar!")

except Exception as e:
    print(f"Fout: {e}")
    sys.exit(1)
