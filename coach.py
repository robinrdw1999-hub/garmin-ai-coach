import os
import json
import time
import smtplib
import sys
import traceback
import urllib.request
import urllib.parse
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

ANALYSEPERIODE_DAGEN = os.environ.get("ANALYSEPERIODE_DAGEN") or "90"
POWERDATA = os.environ.get("POWERDATA") or "soms"
FTP = os.environ.get("FTP") or "onbekend"
MAX_HR = os.environ.get("MAX_HR") or "onbekend"
RUST_HR = os.environ.get("RUST_HR") or "onbekend"
GEWICHT = os.environ.get("GEWICHT") or "72"
FOCUS_CONDITIEANALYSE = os.environ.get("FOCUS_CONDITIEANALYSE") or "wielervorm, koerspunch en herstel"

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
        if str(value).lower() == "onbekend":
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        if str(value).lower() == "onbekend":
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


def summarize_activities(activities):
    current_time = now_be()
    cutoff_7 = current_time - timedelta(days=7)
    cutoff_28 = current_time - timedelta(days=28)
    analysis_days = safe_int(ANALYSEPERIODE_DAGEN, 90)
    cutoff_analysis = current_time - timedelta(days=analysis_days)

    structured = []

    for activity in activities:
        activity_time = parse_garmin_datetime(activity.get("startTimeLocal"))
        type_key = activity.get("activityType", {}).get("typeKey")
        discipline = classify_activity_type(type_key)

        average_power = get_first_available(
            activity,
            [
                "averagePower",
                "avgPower",
                "averageBikePower",
                "avgBikePower"
            ]
        )

        normalized_power = get_first_available(
            activity,
            [
                "normalizedPower",
                "normPower",
                "np"
            ]
        )

        max_power = get_first_available(
            activity,
            [
                "maxPower",
                "maxBikePower"
            ]
        )

        item = {
            "name": activity.get("activityName"),
            "type_key": type_key,
            "discipline": discipline,
            "datetime": activity_time,
            "date": activity_time.strftime("%Y-%m-%d") if activity_time else None,
            "iso_week": activity_time.strftime("%G-W%V") if activity_time else None,
            "distance_m": safe_float(activity.get("distance")),
            "duration_sec": safe_float(activity.get("duration")),
            "average_hr": activity.get("averageHR"),
            "max_hr": activity.get("maxHR"),
            "aerobic_te": activity.get("aerobicTrainingEffect"),
            "anaerobic_te": activity.get("anaerobicTrainingEffect"),
            "average_power": average_power,
            "normalized_power": normalized_power,
            "max_power": max_power,
            "hard": is_hard_session(activity)
        }

        structured.append(item)

    def summarize_since(cutoff, days_window):
        filtered = [
            item for item in structured
            if item["datetime"] and item["datetime"] >= cutoff
        ]

        by_discipline = {}

        for discipline in ["bike", "run", "swim", "strength", "other"]:
            subset = [
                item for item in filtered
                if item["discipline"] == discipline
            ]

            duration_total = sum(item["duration_sec"] for item in subset)
            distance_total = sum(item["distance_m"] for item in subset)

            by_discipline[discipline] = {
                "sessions": len(subset),
                "duration_h": round(duration_total / 3600, 2),
                "distance_km": round(distance_total / 1000, 1)
            }

        training_dates = sorted(set(item["date"] for item in filtered if item["date"]))
        hard_sessions = [item for item in filtered if item["hard"]]

        rest_days_estimate = None
        if days_window == 7:
            rest_days_estimate = max(0, 7 - len(training_dates))

        longest_bike = max(
            [item for item in filtered if item["discipline"] == "bike"],
            key=lambda item: item["duration_sec"],
            default=None
        )

        longest_run = max(
            [item for item in filtered if item["discipline"] == "run"],
            key=lambda item: item["duration_sec"],
            default=None
        )

        longest_swim = max(
            [item for item in filtered if item["discipline"] == "swim"],
            key=lambda item: item["distance_m"],
            default=None
        )

        bike_power_values = [
            safe_float(item["average_power"])
            for item in filtered
            if item["discipline"] == "bike" and item["average_power"] is not None
        ]

        return {
            "total_sessions": len(filtered),
            "total_duration_h": round(sum(item["duration_sec"] for item in filtered) / 3600, 2),
            "hard_sessions": len(hard_sessions),
            "training_days": len(training_dates),
            "rest_days_estimate": rest_days_estimate,
            "by_discipline": by_discipline,
            "bike_avg_power_available_sessions": len(bike_power_values),
            "bike_avg_power_mean": round(sum(bike_power_values) / len(bike_power_values), 1) if bike_power_values else None,
            "longest_bike": {
                "date": longest_bike["date"],
                "duration": format_duration(longest_bike["duration_sec"]),
                "distance_km": km(longest_bike["distance_m"])
            } if longest_bike else None,
            "longest_run": {
                "date": longest_run["date"],
                "duration": format_duration(longest_run["duration_sec"]),
                "distance_km": km(longest_run["distance_m"])
            } if longest_run else None,
            "longest_swim": {
                "date": longest_swim["date"],
                "duration": format_duration(longest_swim["duration_sec"]),
                "distance_km": km(longest_swim["distance_m"])
            } if longest_swim else None
        }

    recent_activities = []

    for item in structured[:10]:
        recent_activities.append({
            "date": item["date"],
            "name": item["name"],
            "discipline": item["discipline"],
            "duration": format_duration(item["duration_sec"]),
            "distance_km": km(item["distance_m"]),
            "avg_hr": item["average_hr"],
            "aerobic_te": item["aerobic_te"],
            "anaerobic_te": item["anaerobic_te"],
            "avg_power": item["average_power"],
            "normalized_power": item["normalized_power"],
            "hard": item["hard"]
        })

    latest = structured[0] if structured else None

    data_quality = {
        "activities_loaded": len(activities),
        "activities_with_datetime": len([item for item in structured if item["datetime"]]),
        "activities_with_hr": len([item for item in structured if item["average_hr"] is not None]),
        "activities_with_training_effect": len([
            item for item in structured
            if item["aerobic_te"] is not None or item["anaerobic_te"] is not None
        ]),
        "bike_activities_with_power": len([
            item for item in structured
            if item["discipline"] == "bike" and item["average_power"] is not None
        ])
    }

    condition_evolution = build_condition_evolution(structured, cutoff_analysis)

    return {
        "data_quality": data_quality,
        "last_7_days": summarize_since(cutoff_7, 7),
        "last_28_days": summarize_since(cutoff_28, 28),
        "condition_evolution": condition_evolution,
        "latest_activity": {
            "date": latest["date"],
            "name": latest["name"],
            "discipline": latest["discipline"],
            "duration": format_duration(latest["duration_sec"]),
            "distance_km": km(latest["distance_m"]),
            "avg_hr": latest["average_hr"],
            "aerobic_te": latest["aerobic_te"],
            "anaerobic_te": latest["anaerobic_te"],
            "avg_power": latest["average_power"],
            "normalized_power": latest["normalized_power"],
            "hard": latest["hard"]
        } if latest else None,
        "recent_activities": recent_activities
    }


def build_condition_evolution(structured, cutoff):
    filtered = [
        item for item in structured
        if item["datetime"] and item["datetime"] >= cutoff
    ]

    weeks = {}

    for item in filtered:
        week = item["iso_week"] or "unknown"

        if week not in weeks:
            weeks[week] = {
                "week": week,
                "total_sessions": 0,
                "total_duration_h": 0.0,
                "hard_sessions": 0,
                "bike_sessions": 0,
                "bike_duration_h": 0.0,
                "bike_distance_km": 0.0,
                "run_sessions": 0,
                "run_duration_h": 0.0,
                "run_distance_km": 0.0,
                "swim_sessions": 0,
                "swim_duration_h": 0.0,
                "bike_power_sessions": 0,
                "bike_avg_power_sum": 0.0,
                "bike_avg_hr_sessions": 0,
                "bike_avg_hr_sum": 0.0
            }

        weeks[week]["total_sessions"] += 1
        weeks[week]["total_duration_h"] += item["duration_sec"] / 3600

        if item["hard"]:
            weeks[week]["hard_sessions"] += 1

        if item["discipline"] == "bike":
            weeks[week]["bike_sessions"] += 1
            weeks[week]["bike_duration_h"] += item["duration_sec"] / 3600
            weeks[week]["bike_distance_km"] += item["distance_m"] / 1000

            if item["average_power"] is not None:
                weeks[week]["bike_power_sessions"] += 1
                weeks[week]["bike_avg_power_sum"] += safe_float(item["average_power"])

            if item["average_hr"] is not None:
                weeks[week]["bike_avg_hr_sessions"] += 1
                weeks[week]["bike_avg_hr_sum"] += safe_float(item["average_hr"])

        if item["discipline"] == "run":
            weeks[week]["run_sessions"] += 1
            weeks[week]["run_duration_h"] += item["duration_sec"] / 3600
            weeks[week]["run_distance_km"] += item["distance_m"] / 1000

        if item["discipline"] == "swim":
            weeks[week]["swim_sessions"] += 1
            weeks[week]["swim_duration_h"] += item["duration_sec"] / 3600

    weekly_trends = []

    for week in sorted(weeks.keys()):
        row = weeks[week]

        bike_avg_power = None
        if row["bike_power_sessions"] > 0:
            bike_avg_power = round(row["bike_avg_power_sum"] / row["bike_power_sessions"], 1)

        bike_avg_hr = None
        if row["bike_avg_hr_sessions"] > 0:
            bike_avg_hr = round(row["bike_avg_hr_sum"] / row["bike_avg_hr_sessions"], 1)

        weekly_trends.append({
            "week": row["week"],
            "total_sessions": row["total_sessions"],
            "total_duration_h": round(row["total_duration_h"], 2),
            "hard_sessions": row["hard_sessions"],
            "bike_sessions": row["bike_sessions"],
            "bike_duration_h": round(row["bike_duration_h"], 2),
            "bike_distance_km": round(row["bike_distance_km"], 1),
            "bike_avg_power": bike_avg_power,
            "bike_avg_hr": bike_avg_hr,
            "run_sessions": row["run_sessions"],
            "run_duration_h": round(row["run_duration_h"], 2),
            "run_distance_km": round(row["run_distance_km"], 1),
            "swim_sessions": row["swim_sessions"],
            "swim_duration_h": round(row["swim_duration_h"], 2)
        })

    recent_weeks = weekly_trends[-4:]
    previous_weeks = weekly_trends[-8:-4]

    def avg(values):
        clean = [value for value in values if value is not None]
        if not clean:
            return None
        return round(sum(clean) / len(clean), 2)

    comparison = {
        "recent_4w_avg_total_duration_h": avg([w["total_duration_h"] for w in recent_weeks]),
        "previous_4w_avg_total_duration_h": avg([w["total_duration_h"] for w in previous_weeks]),
        "recent_4w_avg_bike_duration_h": avg([w["bike_duration_h"] for w in recent_weeks]),
        "previous_4w_avg_bike_duration_h": avg([w["bike_duration_h"] for w in previous_weeks]),
        "recent_4w_avg_hard_sessions": avg([w["hard_sessions"] for w in recent_weeks]),
        "previous_4w_avg_hard_sessions": avg([w["hard_sessions"] for w in previous_weeks]),
        "recent_4w_avg_bike_power": avg([w["bike_avg_power"] for w in recent_weeks]),
        "previous_4w_avg_bike_power": avg([w["bike_avg_power"] for w in previous_weeks])
    }

    return {
        "analysis_period_days": safe_int(ANALYSEPERIODE_DAGEN, 90),
        "athlete_inputs": {
            "powerdata": POWERDATA,
            "ftp": FTP,
            "max_hr": MAX_HR,
            "rust_hr": RUST_HR,
            "gewicht": GEWICHT,
            "focus": FOCUS_CONDITIEANALYSE
        },
        "weekly_trends": weekly_trends,
        "comparison_recent_vs_previous": comparison
    }


def next_races(today):
    result = []

    for race in RACES:
        race_date = datetime.strptime(race["date"], "%Y-%m-%d").date()
        days_until = (race_date - today).days

        if days_until >= 0:
            enriched = dict(race)
            enriched["days_until"] = days_until
            result.append(enriched)

    return result


def determine_training_phase(today):
    current_date = today

    if current_date <= date(2026, 7, 27):
        return {
            "phase": "Bike build met gecontroleerd triatlononderhoud",
            "goal": "Koersspecifieke fietsconditie opbouwen zonder extra loopvermoeidheid.",
            "rules": [
                "Fietsen is hoofdprioriteit.",
                "Zwemmen mag techniek of herstel zijn.",
                "Lopen blijft kort en comfortabel.",
                "Geen zware loopintervallen.",
                "Maximaal twee intensieve fietsprikkels per week.",
                "Geen onnodige bricktrainingen."
            ]
        }

    if date(2026, 7, 28) <= current_date <= date(2026, 7, 31):
        return {
            "phase": "Lichte taper richting Triatlon Donkmeer als plezierwedstrijd",
            "goal": "Fris genoeg blijven voor Donkmeer, zonder echte triatlonpiek te creëren.",
            "rules": [
                "Geen zware looptrainingen.",
                "Korte fietsopeners zijn toegestaan.",
                "Zwemmen alleen technisch en ontspannen.",
                "Geen vermoeidheid creëren voor het wielerblok in augustus.",
                "Triatlonvoorbereiding mag de fietsfocus niet verstoren."
            ]
        }

    if current_date == date(2026, 8, 1):
        return {
            "phase": "Triatlon Donkmeer racedag",
            "goal": "Genieten, gecontroleerd afwerken en geen diepe put graven.",
            "rules": [
                "Triatlon is geen hoofddoel.",
                "Niet forceren in het lopen.",
                "Fietsen stevig maar gecontroleerd.",
                "Na afloop focus op herstel.",
                "Geen extra training naast de wedstrijd."
            ]
        }

    if date(2026, 8, 2) <= current_date <= date(2026, 8, 5):
        return {
            "phase": "Herstel na Triatlon Donkmeer",
            "goal": "Vermoeidheid laten zakken en fietsbenen opnieuw activeren.",
            "rules": [
                "Geen intensieve looptraining.",
                "Geen lange duurtraining.",
                "Lichte fietsritten en herstel zijn prioritair.",
                "Pas intensiteit toevoegen als benen fris aanvoelen.",
                "Focus op herstel richting Haasdonk."
            ]
        }

    if date(2026, 8, 6) <= current_date <= date(2026, 8, 12):
        return {
            "phase": "Laatste koersspecifieke build richting Haasdonk",
            "goal": "Punch, VO2 en herhaalde versnellingen aanscherpen.",
            "rules": [
                "Een of twee korte intensieve fietsprikkels in deze periode.",
                "Geen loopbelasting die fietsfrisheid aantast.",
                "Rustdagen respecteren.",
                "Geen onnodig volume.",
                "Koersspecifiek werken: korte versnellingen, positionering, tempowissels."
            ]
        }

    if date(2026, 8, 13) <= current_date <= date(2026, 8, 16):
        return {
            "phase": "Taper richting Wielerwedstrijd Haasdonk",
            "goal": "Fris, scherp en explosief aan de start komen.",
            "rules": [
                "Volume sterk beperken.",
                "Korte openers, geen zware blokken.",
                "Geen looptraining meer tenzij zeer kort en los.",
                "Slaap en herstel primeren.",
                "Geen training die spierpijn of diepe vermoeidheid kan veroorzaken."
            ]
        }

    if date(2026, 8, 17) <= current_date <= date(2026, 8, 18):
        return {
            "phase": "Herstel na Haasdonk",
            "goal": "Spiervermoeidheid en koersstress laten zakken.",
            "rules": [
                "Alleen herstelrit of rust.",
                "Geen intensiteit.",
                "Geen loopbelasting.",
                "Evalueren hoe diep de wedstrijd zat."
            ]
        }

    if date(2026, 8, 19) <= current_date <= date(2026, 8, 21):
        return {
            "phase": "Aanscherpen richting Sombeke",
            "goal": "Vorm behouden met minimale vermoeidheid.",
            "rules": [
                "Korte intensiteit mag, maar geen lange blokken.",
                "Volume laag houden.",
                "Geen zware krachttraining.",
                "Frisheid is belangrijker dan extra trainingswinst.",
                "Geen looptraining die de fietsbenen belast."
            ]
        }

    if current_date == date(2026, 8, 22):
        return {
            "phase": "Wielerwedstrijd Sombeke racedag",
            "goal": "Koersprestatie maximaliseren.",
            "rules": [
                "Geen extra training.",
                "Korte activatie indien nodig.",
                "Voeding en warming-up concreet houden.",
                "Focus op positionering en herhaalde versnellingen."
            ]
        }

    if date(2026, 8, 23) <= current_date <= date(2026, 8, 24):
        return {
            "phase": "Herstel na Sombeke",
            "goal": "Herstellen zonder vormverlies.",
            "rules": [
                "Rust of zeer lichte fietsrit.",
                "Geen intensiteit.",
                "Geen loopbelasting.",
                "Check vermoeidheid en slaap."
            ]
        }

    if date(2026, 8, 25) <= current_date <= date(2026, 8, 27):
        return {
            "phase": "Aanscherpen richting Atomse Pijl Denderhoutem",
            "goal": "Scherpte behouden voor de funwedstrijd, zonder nog vermoeidheid op te bouwen.",
            "rules": [
                "Korte koersprikkels toegestaan.",
                "Geen lange duurtraining meer.",
                "Geen diepe intervals.",
                "Geen loopbelasting.",
                "Frisheid belangrijker dan extra trainingswinst.",
                "Denderhoutem is een funwedstrijd: scherp starten, maar niet forceren als het lichaam vermoeid is na Haasdonk en Sombeke."
            ]
        }

    if current_date == date(2026, 8, 28):
        return {
            "phase": "Atomse Pijl Denderhoutem racedag",
            "goal": "Koersgericht rijden met focus op fun, positionering en korte versnellingen.",
            "rules": [
                "Geen extra training naast de wedstrijd.",
                "Korte warming-up met enkele korte versnellingen.",
                "Niet starten alsof dit een A-piek is.",
                "Gebruik de wedstrijd als scherpe koersprikkel.",
                "Focus op veilig rijden, positionering en doseren op eventuele selectieve stukken."
            ]
        }

    return {
        "phase": "Post-race overgang",
        "goal": "Herstel, evaluatie en nieuwe doelen bepalen.",
        "rules": [
            "Geen automatische zware opbouw.",
            "Eerst herstelstatus evalueren.",
            "Nieuwe doelstelling bepalen voor volgende blok."
        ]
    }


def determine_recovery_risk(summary, sleep_info, user_feedback):
    reasons = []
    risk_score = 0

    lower_feedback = (user_feedback or "").lower()

    pain_words = [
        "pijn",
        "blessure",
        "knie",
        "achilles",
        "scheen",
        "rug",
        "ziek",
        "koorts",
        "verkouden",
        "oververmoeid",
        "uitgeput",
        "zeer moe",
        "slecht geslapen",
        "zware benen",
        "lege benen",
        "geen energie"
    ]

    for word in pain_words:
        if word in lower_feedback:
            risk_score += 3
            reasons.append("Je feedback bevat een signaal rond pijn, ziekte of duidelijke vermoeidheid.")
            break

    if sleep_info.get("score") is not None:
        score = safe_int(sleep_info.get("score"))

        if score < 60:
            risk_score += 3
            reasons.append(f"Je slaapscore is zeer laag: {score}/100.")
        elif score < 70:
            risk_score += 2
            reasons.append(f"Je slaapscore is laag: {score}/100.")
        elif score < 78:
            risk_score += 1
            reasons.append(f"Je slaapscore is matig: {score}/100.")
        else:
            reasons.append(f"Je slaapscore is bruikbaar tot goed: {score}/100.")
    else:
        risk_score += 1
        reasons.append("De slaapscore ontbreekt, dus de coach trekt geen positieve herstelconclusie.")

    last_7 = summary.get("last_7_days", {})
    hard_sessions = safe_int(last_7.get("hard_sessions"))
    total_h = safe_float(last_7.get("total_duration_h"))
    rest_days = last_7.get("rest_days_estimate")

    if hard_sessions >= 3:
        risk_score += 2
        reasons.append(f"Er staan veel intensieve sessies in de laatste 7 dagen: {hard_sessions}.")
    elif hard_sessions == 2:
        risk_score += 1
        reasons.append("Er staan twee intensieve sessies in de laatste 7 dagen.")
    else:
        reasons.append(f"Het aantal intensieve sessies in de laatste 7 dagen is beperkt: {hard_sessions}.")

    if rest_days is not None and rest_days <= 1:
        risk_score += 1
        reasons.append("Er waren weinig rustdagen in de laatste 7 dagen.")
    elif rest_days is not None:
        reasons.append(f"Geschat aantal rustdagen in de laatste 7 dagen: {rest_days}.")

    if total_h >= 10:
        risk_score += 2
        reasons.append(f"Het totaalvolume van de laatste 7 dagen is hoog: {total_h} uur.")
    elif total_h >= 7:
        risk_score += 1
        reasons.append(f"Het totaalvolume van de laatste 7 dagen is matig tot hoog: {total_h} uur.")
    else:
        reasons.append(f"Het totaalvolume van de laatste 7 dagen blijft beheersbaar: {total_h} uur.")

    if risk_score >= 5:
        level = "hoog"
        allowed = [
            "rust",
            "mobiliteit",
            "zeer lichte herstelrit 30 tot 45 min",
            "easy swim techniek",
            "geen intervals",
            "geen lange duur",
            "geen brick",
            "geen zware looptraining",
            "geen dubbele trainingsdag"
        ]
    elif risk_score >= 3:
        level = "medium"
        allowed = [
            "lichte tot matige training",
            "maximaal korte fietsprikkel als de benen goed voelen",
            "volume niet verhogen",
            "geen zware loopbelasting",
            "geen dubbele trainingsdag",
            "geen diepe intervals"
        ]
    else:
        level = "laag"
        allowed = [
            "normale geplande fietstraining toegestaan",
            "maximaal een hoofdtraining per dag",
            "intensiteit alleen als dit past binnen de fase",
            "looptraining ondergeschikt aan fietsfocus",
            "geen onnodige extra sessies"
        ]

    return {
        "level": level,
        "score": risk_score,
        "reasons": reasons,
        "allowed_training_boundaries": allowed
    }


def build_coach_context(summary, sleep_info, weather, phase, races, recovery):
    today = now_be().date()

    return {
        "today": today.strftime("%Y-%m-%d"),
        "weekday": now_be().strftime("%A"),
        "mode": MODUS,
        "athlete_profile": ATHLETE_PROFILE,
        "athlete_condition_inputs": {
            "analysis_period_days": ANALYSEPERIODE_DAGEN,
            "powerdata": POWERDATA,
            "ftp": FTP,
            "max_hr": MAX_HR,
            "rust_hr": RUST_HR,
            "gewicht": GEWICHT,
            "focus_conditieanalyse": FOCUS_CONDITIEANALYSE
        },
        "upcoming_races": races,
        "current_training_phase": phase,
        "recovery_risk": recovery,
        "sleep": sleep_info,
        "weather": weather,
        "garmin_summary": summary,
        "user_feedback": USER_FEEDBACK,
        "extra_context": EXTRA_CONTEXT,
        "hard_constraints": [
            "Absolute focus ligt op optimale vorm voor de wielerwedstrijden.",
            "Triatlon Donkmeer is plezier en mag geen trainingspiek of grote vermoeidheid veroorzaken.",
            "Haasdonk en Sombeke zijn A-wedstrijden.",
            "Atomse Pijl Denderhoutem is een B/funwedstrijd, geen hoofdpiek.",
            "Geen medische claims.",
            "Bij pijn, ziekte, lage slaapscore of hoge vermoeidheid: training afschalen.",
            "Geen dubbele trainingsdagen voorstellen.",
            "Maximaal een hoofdtraining per dag.",
            "Geen zware looptrainingen in de aanloop naar de wielerwedstrijden.",
            "Bij ontbrekende data expliciet zeggen dat de data ontbreekt.",
            "Advies moet concreet en uitvoerbaar zijn.",
            "Geen heroische taal, geen overdreven motivatie.",
            "Leg altijd kort uit waarom het recovery risk level laag, medium of hoog is."
        ]
    }


def build_prompt(context):
    if MODUS == "week_schema":
        output_instruction = """
Maak een compact weekschema vanaf vandaag tot en met zondag.
Focus op fietsvorm, frisheid en koersspecifieke prikkels.
Geef per dag maximaal een hoofdtraining.
De week mag geen triatlon-focus krijgen.

Neem mee:
- herstelstatus
- belasting laatste 7 dagen
- laatste workout indien relevant
- eerstvolgende wedstrijd
- wanneer intensiteit wel of niet logisch is
"""
        output_structure = """
OUTPUTSTRUCTUUR:

COACH TAKE
Een korte alinea van 2 tot 4 zinnen. Zeg waar de week om draait.

HERSTELSTATUS
- Recovery risk: laag, medium of hoog
- Geef 2 tot 4 concrete redenen waarom dit level geldt.

WEEKDOEL
Leg in 2 tot 4 zinnen uit wat deze week moet opleveren.

WEEKSCHEMA
Geef per dag maximaal één hoofdtraining.
Per dag:
- type dag
- training of rust
- duur
- intensiteit
- aandachtspunt

NIET DOEN DEZE WEEK
Geef 3 tot 5 praktische zaken die de vorm richting de wielerwedstrijden kunnen schaden.

WEDSTRIJDFOCUS
Leg kort de link met Haasdonk, Sombeke, Atomse Pijl Denderhoutem en Triatlon Donkmeer.
"""

    elif MODUS == "race_readiness":
        output_instruction = """
Geef een race-readiness check voor de eerstvolgende wielerwedstrijd.
Focus op frisheid, scherpte, risico's en de laatste 72 uur.

Neem mee:
- recovery risk en concrete reden
- laatste training
- wat nog wel doen
- wat absoluut niet meer doen
- warming-up focus
- koersfocus
"""
        output_structure = """
OUTPUTSTRUCTUUR:

COACH TAKE
Een korte alinea van 2 tot 4 zinnen. Zeg scherp of de atleet vooral moet rusten, aanscherpen of gewoon vertrouwen houden.

READINESS
- Geef een nuchtere inschatting: goed, oké met marge, of voorzichtig.
- Geen percentages verzinnen.

HERSTELSTATUS
- Recovery risk: laag, medium of hoog
- Geef 2 tot 4 concrete redenen waarom dit level geldt.

LAATSTE 72 UUR
Geef concreet wat nog wel en niet moet gebeuren.

WARMING-UP
Geef een korte, praktische warming-up.

KOERSFOCUS
Geef 3 tot 5 koersgerichte aandachtspunten.

NIET DOEN
Geef 3 tot 5 zaken die nu niet slim zijn.
"""

    elif MODUS == "conditie_evolutie":
        output_instruction = """
Maak een grote conditieanalyse over de opgegeven analyseperiode.
Focus op evolutie in tijd, niet op alleen vandaag.
Het doel is begrijpen of de atleet sterker, stabieler of vermoeider wordt richting de wielerwedstrijden.

Neem mee:
- weektrends uit de Garmin-data
- fietsvolume
- intensieve sessies
- koerspunch
- herstelbalans
- loop- en triatlonbelasting
- beschikbare powerdata indien aanwezig
- beperkingen in de data
"""
        output_structure = """
OUTPUTSTRUCTUUR:

SAMENVATTING
Geef in 4 tot 6 bullets de grote lijn:
- conditie stijgend, stabiel of dalend
- fietsvorm
- herstel
- belangrijkste risico richting de wedstrijden

TREND IN TIJD
Analyseer de evolutie per week of per blok.
Gebruik concrete cijfers uit de context waar mogelijk.
Verzin geen cijfers.

FIETSVORM
Bespreek:
- volume
- regelmaat
- langste ritten
- intensieve fietsprikkels
- eventuele powerdata
- of de trend logisch is richting Haasdonk en Sombeke

KOERSPUNCH
Bespreek of er genoeg korte, intensieve of koersspecifieke prikkels zichtbaar zijn.
Als de data dit niet goed toont, zeg dat expliciet.

HERSTELBALANS
Bespreek:
- recovery risk
- slaapdata indien beschikbaar
- rustdagen
- intensieve sessies
- tekenen van opstapelende vermoeidheid

TRIATLONBELASTING
Leg uit of zwemmen en lopen helpen, neutraal zijn of de fietsfocus kunnen verstoren.

WAT BEHOUDEN
Geef 3 tot 5 concrete zaken die goed lopen.

WAT AANPASSEN
Geef 3 tot 5 concrete aanpassingen richting de wielerwedstrijden.

CONCLUSIE VOOR DE KOMENDE 2 WEKEN
Geef een korte coachende conclusie.
"""

    else:
        output_instruction = """
Geef een dagadvies voor vandaag en een target voor morgen.
Deze modus combineert dagadvies, herstelcheck en korte feedback op de laatste workout.

Neem mee:
- recovery risk en concrete reden
- korte feedback op de meest recente Garmin-activiteit
- training vandaag of rust
- target voor morgen
- wat vandaag niet slim is
- link met de wielerwedstrijden
"""
        output_structure = """
OUTPUTSTRUCTUUR:

COACH TAKE
Een korte alinea van 2 tot 4 zinnen. Menselijk, direct en bruikbaar.
Zeg meteen wat vandaag de bedoeling is.

TYPE DAG
Kies 1 label:
- Rustdag
- Hersteldag
- Duurdag
- Koersprikkel
- Openers
- Race day
- Evaluatiedag

HERSTELSTATUS
- Recovery risk: laag, medium of hoog
- Geef 2 tot 4 concrete redenen waarom dit level geldt.
- Gebruik de redenen uit de context. Verzin niets bij.

LAATSTE WORKOUT
- Geef alleen een korte interpretatie als de laatste Garmin-activiteit relevant is.
- Maximaal 3 bullets.
- Leg uit of dit eerder een goede prikkel, onderhoud, herstel of mogelijke vermoeidheidsfactor was.

VANDAAG
- Exacte training of rust
- Duur
- Intensiteit
- Concrete uitvoering in stappen
- Wanneer afbreken of afschalen

WAAROM
Leg kort uit waarom deze training vandaag logisch is richting de wielerwedstrijden.

MORGEN
Geef een target voor morgen. Hou het kort.

NIET DOEN
Geef 2 tot 4 concrete dingen die vandaag niet slim zijn.
Maak dit praktisch, niet generiek.

WEDSTRIJDFOCUS
Leg in 2 tot 4 zinnen de link met Haasdonk, Sombeke, Atomse Pijl Denderhoutem en Triatlon Donkmeer.
"""

    prompt = f"""
Je bent een nuchtere, ervaren wielercoach met basiskennis triatlon.
Je schrijft alsof je jouw atleet kort en duidelijk coacht via mail.
Gebruik gewone coachtaal, geen rapporttaal.

De atleet wil optimaal presteren in de wielerwedstrijden in augustus 2026.
De triatlon op 1 augustus is puur voor het plezier en mag de wielervorm niet schaden.

Toon:
- menselijk
- direct
- kort coachend
- concreet
- licht motiverend
- geen clichés
- geen heroische taal
- geen overdreven peptalk
- geen medische claims

Belangrijk:
- Bij twijfel kies je herstel of lagere intensiteit.
- Adviseer nooit zwaarder dan de recovery boundaries toestaan.
- Maximaal een hoofdtraining per dag.
- Lopen is ondergeschikt aan fietsfrisheid.
- Zwemmen mag vooral herstel of techniek zijn.
- De laatste workout mag benoemd worden, maar maak er geen aparte lange analyse van tenzij die duidelijk relevant is.
- Respecteer expliciet de prioriteit van de wedstrijden:
  1. Haasdonk: A-wedstrijd
  2. Sombeke: A-wedstrijd
  3. Atomse Pijl Denderhoutem: B/funwedstrijd
  4. Triatlon Donkmeer: C/plezierwedstrijd

Vermijd droge formuleringen zoals:
- op basis van de beschikbare data
- hieruit kan geconcludeerd worden
- de belasting suggereert

Gebruik liever coachtaal zoals:
- je hebt genoeg belasting staan
- vandaag niet bewijzen dat je fit bent
- een korte prikkel is genoeg
- frisheid is vandaag belangrijker dan volume
- geen extra loopje toevoegen
- niet van deze sessie een test maken

Specifieke opdracht voor deze run:
{output_instruction}

{output_structure}

Context in JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}
"""

    return prompt


def call_gemini(prompt):
    require_env("GEMINI_API_KEY", GEMINI_API_KEY)

    client = genai.Client(api_key=GEMINI_API_KEY)

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-1.5-flash"
    ]

    last_error = None

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                print(f"Gemini call: {model_name}, poging {attempt + 1}/3")

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )

                text = response.text

                if text and text.strip():
                    return text.strip()

            except Exception as error:
                last_error = error
                error_text = str(error).lower()

                temporary_error = False

                if "503" in error_text:
                    temporary_error = True
                if "unavailable" in error_text:
                    temporary_error = True
                if "rate" in error_text:
                    temporary_error = True
                if "429" in error_text:
                    temporary_error = True
                if "resource_exhausted" in error_text:
                    temporary_error = True

                if temporary_error:
                    time.sleep(10)
                else:
                    raise

    raise Exception(f"Gemini gaf geen bruikbare output. Laatste fout: {last_error}")


def subject_for_mode(context):
    races = context.get("upcoming_races", [])
    next_race = races[0] if races else None

    if next_race:
        race_part = f"{next_race['name']} over {next_race['days_until']} dagen"
    else:
        race_part = "geen komende wedstrijd gevonden"

    if MODUS == "week_schema":
        return f"Wielercoach - weekschema richting {race_part}"

    if MODUS == "race_readiness":
        return f"Wielercoach - race readiness richting {race_part}"

    if MODUS == "conditie_evolutie":
        return f"Wielercoach - conditie-evolutie laatste {safe_int(ANALYSEPERIODE_DAGEN, 90)} dagen"

    return f"Wielercoach - dagadvies richting {race_part}"


def send_email(subject, body):
    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADRES
    msg["To"] = EMAIL_ONTVANGER
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_ADRES, GMAIL_APP_WACHTWOORD)
        server.sendmail(GMAIL_ADRES, EMAIL_ONTVANGER, msg.as_string())


def main():
    require_env("GARMIN_EMAIL", GARMIN_EMAIL)
    require_env("GARMIN_WACHTWOORD", GARMIN_WACHTWOORD)
    require_env("GEMINI_API_KEY", GEMINI_API_KEY)
    require_env("GMAIL_ADRES", GMAIL_ADRES)
    require_env("GMAIL_APP_WACHTWOORD", GMAIL_APP_WACHTWOORD)
    require_env("EMAIL_ONTVANGER", EMAIL_ONTVANGER)

    print("[STAP 1] Inloggen bij Garmin")

    token_dir = os.path.expanduser("~/.garminconnect")
    os.makedirs(token_dir, exist_ok=True)

    garmin = Garmin(GARMIN_EMAIL, GARMIN_WACHTWOORD)
    garmin.login(token_dir)

    print("[STAP 2] Garmin activiteiten ophalen")

    activities_to_fetch = 200 if MODUS == "conditie_evolutie" else 80
    activities = garmin.get_activities(0, activities_to_fetch)

    if not activities:
        raise Exception("Geen Garmin activiteiten gevonden.")

    print("[STAP 3] Slaapdata ophalen")

    sleep_info = get_sleep_info(garmin)

    print("[STAP 4] Weer ophalen")

    weather = get_weather_forecast()

    print("[STAP 5] Activiteiten samenvatten")

    summary = summarize_activities(activities)

    today = now_be().date()
    races = next_races(today)
    phase = determine_training_phase(today)
    recovery = determine_recovery_risk(summary, sleep_info, USER_FEEDBACK)

    context = build_coach_context(
        summary=summary,
        sleep_info=sleep_info,
        weather=weather,
        phase=phase,
        races=races,
        recovery=recovery
    )

    print("[STAP 6] Prompt bouwen")

    prompt = build_prompt(context)

    print("[STAP 7] AI advies genereren")

    ai_text = call_gemini(prompt)

    recovery_reasons = recovery.get("reasons", [])
    recovery_reasons_text = ""

    for reason in recovery_reasons:
        recovery_reasons_text += f"- {reason}\n"

    technical_footer = f"""

--
KORTE DATA-CHECK
Slaapstatus: {sleep_info.get("status")}
Slaapdatum: {sleep_info.get("date")}
Slaapscore: {sleep_info.get("score")}
Recovery risk: {recovery.get("level")} ({recovery.get("score")})

Waarom dit recovery risk level:
{recovery_reasons_text.strip()}

Weerbron: {weather.get("source")} - {weather.get("status")}
Modus: {MODUS}
Analyseperiode conditie: {safe_int(ANALYSEPERIODE_DAGEN, 90)} dagen
Powerdata input: {POWERDATA}
FTP input: {FTP}
Max HR input: {MAX_HR}
Rust-HR input: {RUST_HR}
Gewicht input: {GEWICHT} kg
Garmin activiteiten geladen: {summary.get("data_quality", {}).get("activities_loaded")}
Activiteiten met hartslag: {summary.get("data_quality", {}).get("activities_with_hr")}
Activiteiten met Training Effect: {summary.get("data_quality", {}).get("activities_with_training_effect")}
Fietsactiviteiten met power: {summary.get("data_quality", {}).get("bike_activities_with_power")}
"""

    final_text = ai_text.strip() + technical_footer

    print("[STAP 8] Mail verzenden")

    subject = subject_for_mode(context)

    send_email(subject, final_text)

    print("[SUCCES] Coachadvies verzonden.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("")
        print("CRITICAL ERROR")
        traceback.print_exc()
        print("")
        sys.exit(1)
