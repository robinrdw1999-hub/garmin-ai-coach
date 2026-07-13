import os
import json
import time
import smtplib
import sys
import traceback
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from garminconnect import Garmin
from google import genai

# 1. Omgevingsvariabelen inladen
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_WACHTWOORD = os.environ.get("GARMIN_WACHTWOORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GMAIL_ADRES = os.environ.get("GMAIL_ADRES")
GMAIL_APP_WACHTWOORD = os.environ.get("GMAIL_APP_WACHTWOORD")
EMAIL_ONTVANGER = os.environ.get("EMAIL_ONTVANGER")
EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME")
GEKOZEN_INPUT = os.environ.get("CHOSEN_MODUS")

# Feedback en Weer opvangen
USER_FEEDBACK = os.environ.get("USER_FEEDBACK") or "Geen extra opmerkingen van de renner."
WEATHER_FORECAST = os.environ.get("WEATHER_FORECAST") or "Niet handmatig opgegeven (ga uit van gemiddeld zomerweer)."

MODUS = "week_schema" if EVENT_NAME == "schedule" else GEKOZEN_INPUT

try:
    # 2. Garmin Inloggen
    print("[STAP 1] Inloggen bij Garmin...")
    token_dir = os.path.expanduser("~/.garminconnect")
    os.makedirs(token_dir, exist_ok=True)
    
    garmin = Garmin(GARMIN_EMAIL, GARMIN_WACHTWOORD)
    garmin.login(token_dir)
    
    # 3. Data ophalen (Activiteiten)
    print("[STAP 2] Garmin data ophalen...")
    alle_activiteiten = garmin.get_activities(0, 15) # Iets meer historie voor multi-sport inzicht
    if not alle_activiteiten:
        print("Geen activiteiten gevonden in dit Garmin account.")
        sys.exit(0)
    
    nieuwste_act = alle_activiteiten[0]
    nieuwste_id = nieuwste_act.get("activityId")
    start_time_str = nieuwste_act.get("startTimeLocal")
    
    # Tijdzone-correctie (BE/NL tijd)
    nu_be = datetime.utcnow() + timedelta(hours=2)
    vandaag_str = nu_be.strftime("%Y-%m-%d")
    
    # Slaapscore proberen op te halen
    print("Slaapgegevens ophalen...")
    try:
        sleep_data = garmin.get_sleep_data(vandaag_str)
        slaap_score = sleep_data.get("dailySleepDTO", {}).get("sleepScore", "Onbekend (nog niet gesynct)")
        slaap_kwaliteit = sleep_data.get("dailySleepDTO", {}).get("qualityDescription", "Geen data")
        slaap_info = f"{slaap_score}/100 ({slaap_kwaliteit})"
    except Exception as sleep_err:
        print(f"Slaapscore ophalen mislukt (mogelijk nog geen slaapdata voor vandaag): {sleep_err}")
        slaap_info = "Niet beschikbaar (nog niet gesynct of geen tracking vannacht)"
    
    # Datumpersing activiteit
    clean_time_str = start_time_str[:19].replace("T", " ")
    act_time = datetime.strptime(clean_time_str, "%Y-%m-%d %H:%M:%S")
    
    # 4. Wijzigingscontrole voor automatische dagelijkse runs
    last_id_file = os.path.join(token_dir, "last_activity_id.txt")
    if EVENT_NAME == "schedule":
        if os.path.exists(last_id_file):
            with open(last_id_file, "r") as f:
                if str(f.read().strip()) == str(nieuwste_id):
                    print("Geen nieuwe activiteit sinds de laatste automatische check. We stoppen.")
                    sys.exit(0)

    # 5. Geschiedenis structureren (geschikt voor triatlon: fietsen, lopen, zwemmen)
    content_geschiedenis = []
    for act in alle_activiteiten:
        content_geschiedenis.append({
            "Naam": act.get("activityName"),
            "Type": act.get("activityType", {}).get("typeKey"),
            "Datum": act.get("startTimeLocal"),
            "Afstand (m)": act.get("distance"),
            "Duur (sec)": act.get("duration"),
            "Gemiddelde Hartslag": act.get("averageHR"),
            "Maximale Hartslag": act.get("maxHR"),
            "Aerobe Training Stress": act.get("aerobicTrainingEffect"),
            "Anaerobe Training Stress": act.get("anaerobicTrainingEffect")
        })

    # 6. Dynamische datum- en statusbepaling
    dagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    maanden = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"]
    vandaag_voluit = f"{dagen[nu_be.weekday()]} {nu_be.day} {maanden[nu_be.month - 1]} {nu_be.year}"
    
    rit_datum_str = start_time_str[:10]
    
    if rit_datum_str == vandaag_str:
        training_status = f"De atleet heeft VANDAAG ({vandaag_voluit}) al een sessie afgerond. De nieuwste data staat in het overzicht."
    else:
        training_status = f"De atleet heeft vandaag ({vandaag_voluit}) nog NIET getraind. De meest recente sessie was op {start_time_str}."

    # 7. Gemini AI Aanroepen
    print("[STAP 3] AI Analyse opstarten met Gemini...")
    client = genai.Client(api_key=GEMINI_API_KEY)

    if MODUS == "week_schema":
        subject = "🏊‍♂️ TRIATLON COACH: Jouw Weekschema richting Berlare"
        prompt = f"""Je bent een elite triatloncoach. Jouw atleet bereidt zich voor op zijn hoofddoel: de KWARTTRIATLON VAN BERLARE op zondag 2 augustus 2026 (1500m zwemmen, 40km non-drafting fietsen, 10km hardlopen).

DOELSTELLING: Zorg voor een perfect gebalanceerd, specifiek triatlon-trainingsschema. We moeten de drie disciplines (zwemmen, fietsen, lopen) slim combineren, inclusief herstel en eventuele koppelstrainingen (meteen lopen na het fietsen) om de benen te laten wennen aan de transitie.

⚠️ BIOMETRISCHE & OMGEVINGSMETRICS (GEEF HIER ABSOLUTE PRIORITEIT AAN):
- Vandaag is exact: {vandaag_voluit}
- Status voor vandaag: {training_status}
- Live Garmin Slaapscore van afgelopen nacht: {slaap_info}
- Weersvoorspelling komende dagen: "{WEATHER_FORECAST}"
- Directe feedback van de atleet: "{USER_FEEDBACK}"

INSTRUCTIE METRICS: 
1. Als de slaapscore laag is (<65) of de atleet geeft aan oververmoeid te zijn, pas het schema direct aan naar extra herstel of lagere intensiteit.
2. Pas de trainingen aan op het weer (bijv. bij extreme hitte kortere/vroege sessies, intensiteit hydratatie benadrukken; bij zware regen focus op veiligheid of indoortraining).

Structureer je e-mail EXACT met de volgende hoofdtitels in HOOFDLETTERS:
OPENINGSQUOTE (Een motiverende, scherpe quote passend bij de status van de atleet)

1. DE STATUS EN METRICS CHECK (ANALYSE VAN SLAAP, WEER EN RECENTE WORKOUT)
2. JOUW PERSOONLIJK WEEKSCHEMA (MAANDAG T/M ZONDAG, MET FOCUS OP TARGET WORKOUT VOOR MORGEN)
3. TRIATLON SPECIFIEKE TRANSITIE & WEDSTRIJDSTRATEGIE (TIPS VOOR ZWM/FTS/LPN)

Data recente activiteiten: {json.dumps(content_geschiedenis)}"""

    else:
        subject = "📊 TRIATLON KANSEN CHECKER: Berlare (2 augustus)"
        prompt = f"""Je bent een deskundige triatlon-expert en analist. Evalueer de vorm en de kansen van de atleet voor de Kwarttriatlon van Berlare op 2 augustus 2026 op basis van zijn trainingshistorie en huidige status.
Houd rekening met zijn recente feedback, fitheid en de verzamelde Garmin-data.

Structureer je rapportage in de ik-vorm met deze titels in HOOFDLETTERS:
DE DRIEDUBBELE DIAGNOSE (HET ATLEETPROFIEL PER DISCIPLINE)
REALISTISCH WEDSTRIJDSCENARIO & TIJDPROGNOSE
HET GEVECHTSPLAN VOOR DE WISSELS (T1 & T2 STRATEGIE)

Data recente activiteiten: {json.dumps(content_geschiedenis)}"""

    # Genereren met robuuste retry-logica en fallback-model tegen serverdrukte
    ai_tekst = None
    modellen_om_te_proberen = ['gemini-2.5-flash', 'gemini-1.5-flash']
    
    for model_naam in modellen_om_te_proberen:
        if ai_tekst:
            break
        for poging in range(3):
            try:
                print(f"Aanroepen van {model_naam} (Poging {poging + 1}/3)...")
                response = client.models.generate_content(
                    model=model_naam,
                    contents=prompt,
                )
                ai_tekst = response.text
                if ai_tekst:
                    print(f"[SUCCES] Generatie geslaagd met {model_naam}!")
                    break
            except Exception as e:
                fout_str = str(e).lower()
                if "503" in fout_str or "unavailable" in fout_str or "high demand" in fout_str:
                    print(f"Google servers zijn druk. 10 seconden geduld...")
                    if poging < 2:
                        time.sleep(10)
                else:
                    raise e

    if not ai_tekst:
        raise Exception("Gemini kon niet worden bereikt wegens extreme drukte bij Google.")

    # 8. E-mail Verzenden via SMTP
    print("[STAP 4] Rapportage mailen naar de atleet...")
    msg = MIMEMultipart()
    msg['From'] = GMAIL_ADRES
    msg['To'] = EMAIL_ONTVANGER
    msg['Subject'] = subject
    msg.attach(MIMEText(ai_tekst, 'plain'))

    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(GMAIL_ADRES, GMAIL_APP_WACHTWOORD)
        server.sendmail(GMAIL_ADRES, EMAIL_ONTVANGER, msg.as_string())
    
    # ID opslaan bij automatische runs
    if EVENT_NAME == "schedule":
        with open(last_id_file, "w") as f:
            f.write(str(nieuwste_id))
            
    print("[SUCCES] Triatlon-analyse succesvol verzonden!")

except Exception as e:
    print("\n" + "="*50)
    print("🚨 ER IS EEN CRITICAL ERROR OPGETREDEN 🚨")
    print("="*50)
    traceback.print_exc()
    print("="*50 + "\n")
    sys.exit(1)
