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

# Feedback van de renner opvangen
USER_FEEDBACK = os.environ.get("USER_FEEDBACK")
if not USER_FEEDBACK or USER_FEEDBACK.strip() == "":
    USER_FEEDBACK = "Geen extra opmerkingen van de renner voor deze run."

MODUS = "auto_coach" if EVENT_NAME == "schedule" else GEKOZEN_INPUT

try:
    # 2. Garmin Inloggen
    print("[STAP 1] Inloggen bij Garmin...")
    token_dir = os.path.expanduser("~/.garminconnect")
    os.makedirs(token_dir, exist_ok=True)
    
    garmin = Garmin(GARMIN_EMAIL, GARMIN_WACHTWOORD)
    garmin.login(token_dir)
    
    # 3. Data ophalen
    print("[STAP 2] Activiteiten ophalen...")
    alle_activiteiten = garmin.get_activities(0, 10)
    if not alle_activiteiten:
        print("Geen activiteiten gevonden in dit Garmin account.")
        sys.exit(0)
    
    nieuwste_act = alle_activiteiten[0]
    nieuwste_id = nieuwste_act.get("activityId")
    start_time_str = nieuwste_act.get("startTimeLocal")
    
    # Tijdzone-correctie (BE/NL tijd)
    nu_be = datetime.utcnow() + timedelta(hours=2)
    
    # Maak de datumpersing robuust voor zowel 'YYYY-MM-DD HH:MM:SS' als 'YYYY-MM-DDTHH:MM:SS.0'
    clean_time_str = start_time_str[:19].replace("T", " ")
    act_time = datetime.strptime(clean_time_str, "%Y-%m-%d %H:%M:%S")
    
    # 4. Wijzigings- en tijdcontrole voor automatische ritten
    last_id_file = os.path.join(token_dir, "last_activity_id.txt")
    if MODUS == "auto_coach":
        if os.path.exists(last_id_file):
            with open(last_id_file, "r") as f:
                if str(f.read().strip()) == str(nieuwste_id):
                    print("Activiteit al eerder geanalyseerd. We stoppen om spam te voorkomen.")
                    sys.exit(0)
        
        if nu_be - act_time > timedelta(minutes=90):
            print("Nieuwste activiteit is ouder dan 90 minuten. Geen actie vereist.")
            sys.exit(0)

    # 5. Geschiedenis structureren
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
    vandaag_str = nu_be.strftime("%Y-%m-%d")
    
    if rit_datum_str == vandaag_str:
        training_status = f"De renner heeft VANDAAG ({vandaag_voluit}) al getraind. De nieuwste sessie staat in de data."
    else:
        training_status = f"De renner heeft vandaag ({vandaag_voluit}) nog NIET getraind. De meest recente sessie is van gisteren of eerder ({start_time_str})."

    # 7. Gemini AI Aanroepen via de nieuwe GenAI Client
    print("[STAP 3] AI Analyse opstarten met Gemini...")
    client = genai.Client(api_key=GEMINI_API_KEY)

    if MODUS in ["auto_coach", "resterende_dagen"]:
        subject = "🚀 WIJTSCHAETE PREP: Jouw Anaerobe Schema"
        prompt = f"""Je bent een elite wielercoach. De renner heeft op zaterdag 11 juli 2026 de 'Wijtschaete koers' (kermiskoer).

DOELSTELLING: De renner heeft een sterke motor (FTP/aeroob), maar is recent snel uit koers gereden omdat hij kraakte op de constante spurts i.v.m. herlanceringen na de bochten (Repeated Sprint Ability / Anaerobe capaciteit schiet tekort). We gaan hem nu transformeren in een criterium-specialist.

⚠️ STRIKTE SUBJECTIEVE FEEDBACK VAN DE RENNER (GEEF HIER ABSOLUTE PRIORITEIT AAN):
"{USER_FEEDBACK}"
(Instructie voor de AI: Als de renner aangeeft overtraind/moe te zijn, schrijf dan direct actieve recuperatie of rust voor, ongeacht wat de periodisering zegt. Als de renner aangeeft dat zijn hartslagmeter defect is, negeer dan vreemde hartslagpieken of -dalen in de recente data en baseer je advies op gevoel/duur/afstand).

REMAN OP DE RECENTE TRAINING: Let op, de renner kan ook loopsessies of alternatieve trainingen uitvoeren als cross-training. Neem dit mee in je analyse als actieve recuperatie of conditionele prikkel.

TIMING & STATUS:
- Vandaag is exact: {vandaag_voluit}
- Status voor vandaag: {training_status}

STRIKTE PERIODISERING (RECONCILIEER MET GEBLOKKEERDE DAGEN EN DE FEEDBACK):
1. BLOCK 1 (Nu t/m 30 juni): Rammen op anaerobe herhaalbaarheid. Schrijf loeiharde kermiskoer-simulaties voor (bijv. Tabata's, 30/30s, 40/20s, of 15-seconden maximale sprints vanuit lage snelheid om bochten te simuleren).
2. BLOCK 2 (Woensdag 1 juli t/m zondag 5 juli): DE RENNER KAN NIET TRAINEN (Vakantie/Verplichtingen). Plan hier absoluut GEEN trainingen in. Noem dit expliciet een gedwongen de-load periode voor supercompensatie.
3. BLOCK 3 (6 juli t/m 10 juli): Re-activatie. Korte, felle ritten met korte prikkels om de spiertonus bliksemsnel terug te halen voor de koers op zaterdag 11 juli.

Structureer je e-mail EXACT met de volgende hoofdtitels in HOOFDLETTERS:
OPENINGSQUOTE

1. DE DIAGNOSE VAN HET TEKORT (ANALYSE LAATSTE TRAINING & JOUW FEEDBACK)
2. JOUW SPECIFIEKE TARGET WORKOUT VOOR MORGEN (MET CONCRETE INTENSITEITEN)
3. DE ROUTE NAAR WIJTSCHAETE (PERIODISERING EN STRATEGIE)

Data: {json.dumps(content_geschiedenis)}"""

    else:
        subject = "📊 KANSEN CHECKER: Wijtschaete koers (11 juli)"
        prompt = f"""Je bent een deskundige, nuchtere Belgische ploegleider. Evalueer de kansen van de renner (72kg) voor Wijtschaete koers op zaterdag 11 juli 2026.
Onthoud dat zijn basismotor sterk is, maar dat de herlanceringen na de bocht zijn zwakke punt zijn, én dat hij van 1 t/m 5 juli volledig stilzit.

⚠️ RECENTE OPMERKING VAN DE RENNER:
"{USER_FEEDBACK}"

Structureer je rapportage in de ik-vorm met deze titels in HOOFDLETTERS:
DE RAUWE DIAGNOSE (HET RENNERSPROFIEL)
REALISTISCH KOERSSCENARIO & KANSBEREKENING
Geef procentuele kansen op:
- % Kans op actieve koers (meeschuiven/aanvallen)
- % Kans op pelotonfinish
- % Kans op vroege deconnexie

HET TACTISCHE GEVECHTSPLAN

Data: {json.dumps(content_geschiedenis)}"""

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
                    print(f"Google geeft aan dat {model_naam} overbelast is. Even geduld...")
                    if poging < 2:
                        time.sleep(10)
                else:
                    raise e

    if not ai_tekst:
        raise Exception("Gemini kon niet worden bereikt na meerdere pogingen wegens extreme drukte bij Google.")

    # 8. E-mail Verzenden via SMTP
    print("[STAP 4] Rapportage mailen naar de renner...")
    msg = MIMEMultipart()
    msg['From'] = GMAIL_ADRES
    msg['To'] = EMAIL_ONTVANGER
    msg['Subject'] = subject
    msg.attach(MIMEText(ai_tekst, 'plain'))

    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(GMAIL_ADRES, GMAIL_APP_WACHTWOORD)
        server.sendmail(GMAIL_ADRES, EMAIL_ONTVANGER, msg.as_string())
    
    # Bij succesvolle auto-run: ID opslaan
    if MODUS == "auto_coach":
        with open(last_id_file, "w") as f:
            f.write(str(nieuwste_id))
            
    print("[SUCCES] Workflow volledig en correct doorlopen!")

except Exception as e:
    print("\n" + "="*50)
    print("🚨 ER IS EEN CRITICAL ERROR OPGETREDEN 🚨")
    print("="*50)
    traceback.print_exc()
    print("="*50 + "\n")
    sys.exit(1)
