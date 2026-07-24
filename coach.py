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
                    profile_payloads.append({
                        "method": method_name,
                        "payload": payload
                    })
        except Exception:
            pass

    for item in profile_payloads:
        payload = item["payload"]
        method_name = item["method"]

        if result["ftp"] is None:
            ftp_value = recursive_find(
                payload,
                [
                    "functionalThresholdPower",
                    "ftp",
                    "cyclingFtp",
                    "bikeFtp",
                    "thresholdPower"
                ]
            )

            if ftp_value is not None:
                ftp_int = safe_int(ftp_value, default=0)
                if ftp_int > 0:
                    result["ftp"] = ftp_int
                    result["ftp_source"] = method_name

        if result["max_hr"] is None:
            max_hr_value = recursive_find(
                payload,
                [
                    "maxHeartRate",
                    "maximumHeartRate",
                    "maxHR",
                    "maxHr"
                ]
            )

            if max_hr_value is not None:
                max_hr_int = safe_int(max_hr_value, default=0)
                if max_hr_int > 0:
                    result["max_hr"] = max_hr_int
                    result["max_hr_source"] = method_name

    max_hr_values = []
    power_sessions = 0

    for activity in activities:
        type_key = activity.get("activityType", {}).get("typeKey")
        discipline = classify_activity_type(type_key)

        if activity.get("maxHR") is not None:
            max_hr_values.append(safe_int(activity.get("maxHR")))

        if discipline == "bike":
            avg_power = get_first_available(
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

            if avg_power is not None or normalized_power is not None:
                power_sessions += 1

            if result["ftp"] is None:
                ftp_value = recursive_find(
                    activity,
                    [
                        "functionalThresholdPower",
                        "ftp",
                        "cyclingFtp",
                        "bikeFtp",
                        "thresholdPower"
                    ]
                )

                if ftp_value is not None:
                    ftp_int = safe_int(ftp_value, default=0)
                    if ftp_int > 0:
                        result["ftp"] = ftp_int
                        result["ftp_source"] = "Garmin activity list"

    if result["ftp"] is None:
        bike_activity_ids = []

        for activity in activities[:30]:
            type_key = activity.get("activityType", {}).get("typeKey")
            discipline = classify_activity_type(type_key)

            if discipline == "bike":
                activity_id = activity.get("activityId")
                if activity_id:
                    bike_activity_ids.append(activity_id)

        for activity_id in bike_activity_ids[:10]:
            try:
                if hasattr(garmin, "get_activity_details"):
                    details = garmin.get_activity_details(activity_id)

                    ftp_value = recursive_find(
                        details,
                        [
                            "functionalThresholdPower",
                            "ftp",
                            "cyclingFtp",
                            "bikeFtp",
                            "thresholdPower"
                        ]
                    )

                    if ftp_value is not None:
                        ftp_int = safe_int(ftp_value, default=0)
                        if ftp_int > 0:
                            result["ftp"] = ftp_int
                            result["ftp_source"] = f"Garmin activity details {activity_id}"
                            break
            except Exception:
                pass

    if result["max_hr"] is None and max_hr_values:
        plausible_values = [
            value for value in max_hr_values
            if value and 120 <= value <= 220
        ]

        if plausible_values:
            result["max_hr"] = max(plausible_values)
            result["max_hr_source"] = "hoogste maxHR uit recente Garmin activiteiten"

    result["power_sessions_detected"] = power_sessions

    if power_sessions >= 5:
        result["powerdata"] = "ja"
    elif power_sessions > 0:
        result["powerdata"] = "soms"
    else:
        result["powerdata"] = "nee of niet zichtbaar in Garmin activity list"

    if result["ftp"] is None:
        result["ftp"] = "niet gevonden"

    if result["resting_hr"] is None:
        result["resting_hr"] = "niet gevonden"

    if result["max_hr"] is None:
        result["max_hr"] = "niet gevonden"

    return result


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

    
