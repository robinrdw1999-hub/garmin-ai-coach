import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from garminconnect import Garmin
from google import genai

# Gegevens veilig ophalen uit de GitHub kluis
GARMIN_EMAIL = os.environ.get('GARMIN_EMAIL')
GARMIN_WACHTWOORD = os.environ.get('GARMIN_WACHTWOORD')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GMAIL_ADRES = os.environ.get('GMAIL_ADRES')
GMAIL_APP_WACHTWOORD = os.environ.get('GMAIL_APP_WACHTWOORD')
EMAIL_ONTVANGER = os.environ.get('EMAIL_ONTVANGER')

def haal_laatste_training_op():
    try:
        garmin = Garmin(GARMIN_EMAIL, GARMIN_WACHTWOORD)
        garmin.login()
        activiteiten = garmin.get_activities(0, 1)
        return activiteiten[0] if activiteiten else None
    except Exception as e:
        print(f"Garmin fout: {e}")
        return None

def analyseer_met_gemini(activiteit_data):
    relevante_data = {
        "Naam": activiteit_data.get("activityName"),
        "Type": activiteit_data.get("activityType", {}).get("typeKey"),
        "Datum": activiteit_data.get("startTimeLocal"),
        "Afstand (m)": activiteit_data.get("distance"),
        "Duur (sec)": activiteit_data.get("duration"),
        "Gemiddelde Hartslag": activiteit_data.get("averageHR"),
        "Maximale Hartslag": activiteit_data.get("maxHR"),
        "Calorieën": activiteit_data.get("calories"),
        "Gemiddelde Snelheid": activiteit_data.get("averageSpeed"),
        "Aerobe Training Stress": activiteit_data.get("aerobicTrainingEffect")
    }

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"Je bent een hardloopcoach. Analyseer deze training kort en motiverend met hersteladvies: {json.dumps(relevante_data)}"
    response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
    return response.text

def stuur_email(analyse_tekst, activiteit_naam):
    try:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_ADRES
        msg['To'] = EMAIL_ONTVANGER
        msg['Subject'] = f"🏃‍♂️ Automatische AI Analyse: {activiteit_naam}"
        msg.attach(MIMEText(analyse_tekst, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_ADRES, GMAIL_APP_WACHTWOORD)
        server.sendmail(GMAIL_ADRES, EMAIL_ONTVANGER, msg.as_string())
        server.quit()
        print("Mail verzonden!")
    except Exception as e:
        print(f"Mail fout: {e}")

data = haal_laatste_training_op()
if data:
    analyse = analyseer_met_gemini(data)
    stuur_email(analyse, data.get("activityName", "Training"))
