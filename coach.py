import os
import json
import time
import smtplib
import sys
import traceback
import urllib.request
import urllib.parse
import shutil
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from garminconnect import Garmin
from google import genai


TIMEZONE = ZoneInfo("Europe/Brussels")

GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_WACHTWOORD = os.environ.get("GARMIN_WACHTWOORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

GMAIL_ADRES = os.environ.get("GMAIL_ADRES")
GMAIL_APP_WACHTWOORD = os.environ.get("GMAIL_APP_WACHTWOORD")
EMAIL_ONTVANGER = os.environ.get("EMAIL_ONTVANGER")

EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "manual")
GEKOZEN_MODUS = os.environ.get("CHOSEN_MODUS") or "dagadvies"

USER_FEEDBACK = os.environ.get("USER_FEEDBACK") or "Geen actuele subjectieve feedback opgegeven."
EXTRA_CONTEXT = os.environ.get("EXTRA_CONTEXT") or ""

MODUS = "dagadvies" if EVENT_NAME == "schedule" else GEKOZEN_MODUS

ANALYSEPERIODE_DAGEN = "90"
GEWICHT = "72"
FOCUS_CONDITIEANALYSE = "wielervorm, koerspunch en herstel"

WEATHER_LAT = 51.03
WEATHER_LON = 4.10

ATHLETE_PROFILE = {
    "focus": "optimale vorm voor wielerwedstrijden",
    "triathlon_priority": "Triatlon Donkmeer is puur voor het plezier en mag de wielervorm niet hypothekeren.",
    "tone": "nuchter, menselijk, direct en licht coachend",
    "max_main_sessions_per_day": 1
}

RACES = [
    {
        "date": "2026-08-01",
        "name": "Triatlon Donkmeer",
        "type": "triathlon_fun",
        "priority": "C",
        "note": "Plezierwedstrijd. Niet pieken. Geen agressieve taper. Geen onnodige loopbelasting vooraf."
    },
    {
        "date": "2026-08-16",
        "name": "Wielerwedstrijd Haasdonk",
        "type": "cycling_race",
        "priority": "A",
        "note": "Eerste hoofddoel. Frisheid, koershardheid en punch zijn prioritair."
    },
    {
        "date": "2026-08-22",
        "name": "Wielerwedstrijd Sombeke",
        "type": "cycling_race",
        "priority": "A",
        "note": "Tweede hoofddoel. Vorm onderhouden, niet opnieuw zware opbouw starten."
    },
    {
        "date": "2026-08-28",
        "name": "Atomse Pijl Denderhoutem",
        "type": "cycling_fun_race",
        "priority": "B",
        "note": "Funwedstrijd Cycling Vlaanderen. Koersgericht rijden, maar niet behandelen als hoofdpiek."
    }
]


def require_env(name, value):
    if not value:
        raise Exception(f"Ontbrekende environment variable of secret: {name}")


def now_be():
    return datetime.now(TIMEZONE)


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        if str(value).lower() in ["onbekend", "niet gevonden"]:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        if str(value).lower() in ["onbekend", "niet gevonden"]:
            return default
        return int(float(value))
    except Exception:
        return default


def format_duration(seconds):
    seconds = safe_float(seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)

    if hours > 0:
        return f"{hours}u{minutes:02d}"

    return f"{minutes} min"


def km(meters):
    return round(safe_float(meters) / 1000, 1)


def parse_garmin_datetime(value):
    if not value:
        return None

    cleaned = str(value)[:19].replace("T", " ")

    try:
        return datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE)
    except Exception:
        return None


def recursive_find(data, keys):
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]

        for value in data.values():
            found = recursive_find(value, keys)
            if found is not None:
                return found

    if isinstance(data, list):
        for item in data:
            found = recursive_find(item, keys)
            if found is not None:
                return found

    return None


def get_first_available(activity, keys):
    for key in keys:
        if key in activity and activity[key] is not None:
            return activity[key]
    return None


def classify_activity_type(type_key):
    if not type_key:
        return "other"

    t = str(type_key).lower()

    if "run" in t:
        return "run"

    if "cycling" in t or "biking" in t or "ride" in t or "bike" in t:
        return "bike"

    if "swim" in t:
        return "swim"

    if "strength" in t or "hiit" in t or "cardio" in t:
        return "strength"

    return "other"


def is_hard_session(activity):
    aerobic = safe_float(activity.get("aerobicTrainingEffect"))
    anaerobic = safe_float(activity.get("anaerobicTrainingEffect"))
    average_hr = safe_float(activity.get("averageHR"))
    duration = safe_float(activity.get("duration"))

    if anaerobic >= 2.0:
        return True

    if aerobic >= 3.5:
        return True

    if average_hr >= 160 and duration >= 1800:
        return True

    return False


def login_garmin_with_retry():
    token_dir = os.path.expanduser("~/.garminconnect")
    os.makedirs(token_dir, exist_ok=True)

    print("[GARMIN] Login proberen met bestaande token/cache")

    try:
        garmin = Garmin(GARMIN_EMAIL, GARMIN_WACHTWOORD)
        garmin.login(token_dir)
        print("[GARMIN] Login gelukt")
        return garmin

    except Exception as first_error:
        print("[GARMIN] Eerste loginpoging mislukt")
        print(f"[GARMIN] Fout: {str(first_error)}")
        print("[GARMIN] Oude Garmin token/cache wordt verwijderd en login wordt opnieuw geprobeerd")

        try:
            if os.path.exists(token_dir):
                shutil.rmtree(token_dir)

            os.makedirs(token_dir, exist_ok=True)

            garmin = Garmin(GARMIN_EMAIL, GARMIN_WACHTWOORD)
            garmin.login(token_dir)

            print("[GARMIN] Login gelukt na verwijderen van token/cache")
            return garmin

        except Exception as second_error:
            print("[GARMIN] Tweede loginpoging ook mislukt")
            print("[GARMIN] Mogelijke oorzaken:")
            print("- Garmin wachtwoord is gewijzigd")
            print("- GARMIN_EMAIL of GARMIN_WACHTWOORD secret is fout")
            print("- Garmin vraagt opnieuw MFA/2FA")
            print("- Garmin Connect blokkeert tijdelijk de login")
            print("- Garmin API geeft tijdelijk 401/403 terug")

            raise second_error


def get_sleep_info(garmin):
    dates_to_try = [
        now_be().date(),
        now_be().date() - timedelta(days=1)
    ]

    attempts = []

    for day in dates_to_try:
        day_string = day.strftime("%Y-%m-%d")

        try:
            sleep_data = garmin.get_sleep_data(day_string)

            attempts.append({
                "date": day_string,
                "raw_available": bool(sleep_data)
            })

            if not sleep_data:
                continue

            score = None
            quality = None

            daily = sleep_data.get("dailySleepDTO", {}) if isinstance(sleep_data, dict) else {}

            if isinstance(daily, dict):
                score = daily.get("sleepScore")

                if score is None:
                    scores = daily.get("sleepScores", {})
                    if isinstance(scores, dict):
                        overall = scores.get("overall", {})
                        if isinstance(overall, dict):
                            score = overall.get("value")

                quality = daily.get("qualityDescription")
                if quality is None:
                    quality = daily.get("sleepScoreFeedback")
                if quality is None:
                    quality = daily.get("sleepQuality")

            if score is None:
                score = recursive_find(
                    sleep_data,
                    [
                        "sleepScore",
                        "overallSleepScore",
                        "sleepScoreValue"
                    ]
                )

            if quality is None:
                quality = recursive_find(
                    sleep_data,
                    [
                        "qualityDescription",
                        "sleepScoreFeedback",
                        "sleepQualityType",
                        "sleepQuality"
                    ]
                )

            if score is not None:
                score_int = safe_int(score, default=-1)

                if score_int >= 0:
                    return {
                        "status": "beschikbaar",
                        "date": day_string,
                        "score": score_int,
                        "quality": quality or "Geen kwaliteitslabel gevonden",
                        "note": "Slaapscore gelezen uit Garmin sleep data."
                    }

        except Exception as error:
            attempts.append({
                "date": day_string,
                "error": str(error)
            })

    return {
        "status": "niet beschikbaar",
        "date": None,
        "score": None,
        "quality": None,
        "note": "Slaapscore kon niet betrouwbaar gelezen worden. Mogelijke oorzaken: Garmin nog niet gesynchroniseerd, geen slaapscore in account, of gewijzigde structuur in Garmin Connect.",
        "attempts": attempts
    }


def get_weather_forecast():
    try:
        base_url = "https://api.open-meteo.com/v1/forecast"

        params = {
            "latitude": WEATHER_LAT,
            "longitude": WEATHER_LON,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
            "timezone": "Europe/Brussels",
            "forecast_days": 5
        }

        url = base_url + "?" + urllib.parse.urlencode(params)

        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        daily = data.get("daily", {})
        days = daily.get("time", [])
        tmax = daily.get("temperature_2m_max", [])
        tmin = daily.get("temperature_2m_min", [])
        rain = daily.get("precipitation_probability_max", [])
        wind = daily.get("wind_speed_10m_max", [])

        forecast = []

        for index, day in enumerate(days):
            forecast.append({
                "date": day,
                "temp_min_c": tmin[index] if index < len(tmin) else None,
                "temp_max_c": tmax[index] if index < len(tmax) else None,
                "rain_probability_pct": rain[index] if index < len(rain) else None,
                "max_wind_kmh": wind[index] if index < len(wind) else None
            })

        return {
            "source": "Open-Meteo",
            "status": "beschikbaar",
            "forecast": forecast
        }

    except Exception as error:
        return {
            "source": "Open-Meteo",
            "status": "niet beschikbaar",
            "error": str(error),
            "forecast": []
        }


def detect_athlete_metrics(garmin, activities):
    result = {
        "ftp": None,
        "ftp_source": None,
        "resting_hr": None,
        "resting_hr_source": None,
        "max_hr": None,
        "max_hr_source": None,
        "powerdata": "niet gevonden",
        "power_sessions_detected": 0,
        "weight_kg": GEWICHT
    }

    today = now_be().date()
    dates_to_try = [
        today,
        today - timedelta(days=1),
        today - timedelta(days=2),
        today - timedelta(days=3),
        today - timedelta(days=4),
        today - timedelta(days=5),
        today - timedelta(days=6)
    ]

    for day in dates_to_try:
        day_string = day.strftime("%Y-%m-%d")

        if result["resting_hr"] is None:
            try:
                if hasattr(garmin, "get_user_summary"):
                    summary = garmin.get_user_summary(day_string)
                    resting = recursive_find(
                        summary,
                        [
                            "restingHeartRate",
                            "restingHR",
                            "restingHr",
                            "minHeartRate"
                        ]
                    )

                    if resting is not None:
                        resting_int = safe_int(resting, default=0)
                        if resting_int > 0:
                            result["resting_hr"] = resting_int
                            result["resting_hr_source"] = f"Garmin user summary {day_string}"
            except Exception:
                pass

        if result["resting_hr"] is None:
            try:
                if hasattr(garmin, "get_heart_rates"):
                    hr_data = garmin.get_heart_rates(day_string)
                    resting = recursive_find(
                        hr_data,
                        [
                            "restingHeartRate",
                            "restingHR",
                            "restingHr",
                            "minHeartRate"
                        ]
                    )

                    if resting is not None:
                        resting_int = safe_int(resting, default=0)
                        if resting_int > 0:
                            result["resting_hr"] = resting_int
                            result["resting_hr_source"] = f"Garmin heart rate data {day_string}"
            except Exception:
                pass

    possible_profile_methods = [
        "get_user_profile",
        "get_user_settings"
    ]

    profile_payloads = []

    for method_name in possible_profile_methods:
        try:
            if hasattr(garmin, method_name):
                method = getattr(garmin, method_name)
                payload = method()

                if payload:
                    profile
