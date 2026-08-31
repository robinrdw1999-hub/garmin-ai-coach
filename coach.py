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

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_WACHTWOORD = os.getenv("GARMIN_WACHTWOORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GMAIL_ADRES = os.getenv("GMAIL_ADRES")
GMAIL_APP_WACHTWOORD = os.getenv("GMAIL_APP_WACHTWOORD")
EMAIL_ONTVANGER = os.getenv("EMAIL_ONTVANGER")

EVENT_NAME = os.getenv("GITHUB_EVENT_NAME", "manual")
GEKOZEN_MODUS = os.getenv("CHOSEN_MODUS") or "dagadvies"

USER_FEEDBACK = (
    os.getenv("USER_FEEDBACK")
    or "Geen actuele subjectieve feedback opgegeven."
)

EXTRA_CONTEXT = os.getenv("EXTRA_CONTEXT") or ""

MODUS = (
    "dagadvies"
    if EVENT_NAME == "schedule"
    else GEKOZEN_MODUS
)

ANALYSEPERIODE_DAGEN = 180
GEWICHT = 72

WEATHER_LAT = 51.03
WEATHER_LON = 4.10


SEASON_CONFIG = {
    "preparation_start": "2026-10-01",
    "race_season_start": "2027-05-01",
    "race_season_end": "2027-09-15",
    "target_race_count_min": 12,
    "target_race_count_max": 16,
    "max_consecutive_race_weekends": 2,
    "target_a_races_min": 3,
    "target_a_races_max": 4,
    "discipline": "criterium- en wegwedstrijden",
    "main_goal": "allround wielerprestatie ontwikkelen",
    "development_goals": [
        "gezond en consistent kunnen trainen",
        "aerobe basis en duurzaamheid verbeteren",
        "FTP en tijd tot uitputting rond drempel verbeteren",
        "VO2max en herhaalde inspanningen boven drempel verbeteren",
        "anaerobe capaciteit, acceleraties en sprint ontwikkelen",
        "vermogen laat in een rit beter behouden",
        "techniek, positionering, bochten en koersinzicht ontwikkelen",
        "frisheid rond prioritaire wedstrijden bewaken"
    ]
}


ATHLETE_PROFILE = {
    "weight_kg": GEWICHT,
    "primary_sport": "wielrennen",
    "main_objective": (
        "De best mogelijke allround renner worden voor criterium- "
        "en wegwedstrijden. FTP is belangrijk, maar is slechts "
        "een bouwsteen."
    ),
    "performance_hierarchy": [
        "gezondheid, continuïteit en herstelbaarheid",
        "aerobe basis en duurzaamheid",
        "FTP en drempelduur",
        "VO2max en herhaalde hoge intensiteit",
        "anaerobe capaciteit, acceleratie en sprint",
        "techniek en koersvaardigheid",
        "wedstrijdspecifieke frisheid"
    ],
    "other_sports": (
        "Alleen aanvullend en niet ten koste van fietskwaliteit "
        "of herstel."
    ),
    "max_main_sessions_per_day": 1,
    "max_quality_sessions_per_week": 2,
    "default_block_structure": (
        "Meestal drie opbouwweken en één herstelweek, "
        "maar hersteldata gaan voor."
    ),
    "benchmark_frequency": (
        "Hoogstens om de zes tot acht weken, met hetzelfde "
        "protocol en dezelfde vermogensbron."
    ),
    "tone": "nuchter, menselijk, direct en licht coachend"
}


# Vul alleen echte wedstrijden in zodra de kalender bekend is.
RACES = [
    # Voorbeeld:
    #
    # {
    #     "date": "2027-05-09",
    #     "name": "Naam wedstrijd",
    #     "type": "cycling_race",
    #     "priority": "C",
    #     "note": "Vroege seizoenswedstrijd als koersprikkel."
    # }
]


def require_env(name, value):
    if not value:
        raise RuntimeError(
            f"Ontbrekende environment variable of secret: {name}"
        )


def now_be():
    return datetime.now(TIMEZONE)


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if str(value).lower() in {
            "onbekend",
            "niet gevonden"
        }:
            return default

        return float(value)

    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default

        if str(value).lower() in {
            "onbekend",
            "niet gevonden"
        }:
            return default

        return int(float(value))

    except (TypeError, ValueError):
        return default


def recursive_find(data, keys):
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]

        for value in data.values():
            found = recursive_find(value, keys)

            if found is not None:
                return found

    elif isinstance(data, list):
        for item in data:
            found = recursive_find(item, keys)

            if found is not None:
                return found

    return None


def parse_garmin_datetime(value):
    if not value:
        return None

    try:
        cleaned = str(value)[:19].replace("T", " ")

        return datetime.strptime(
            cleaned,
            "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=TIMEZONE)

    except ValueError:
        return None


def format_duration(seconds):
    seconds = safe_float(seconds)

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)

    if hours:
        return f"{hours}u{minutes:02d}"

    return f"{minutes} min"


def classify_activity_type(type_key):
    text = str(type_key or "").lower()

    if "run" in text:
        return "run"

    if any(
        term in text
        for term in (
            "cycling",
            "biking",
            "ride",
            "bike"
        )
    ):
        return "bike"

    if "swim" in text:
        return "swim"

    if any(
        term in text
        for term in (
            "strength",
            "hiit",
            "cardio"
        )
    ):
        return "strength"

    return "other"


def is_hard_session(activity):
    aerobic = safe_float(
        activity.get("aerobicTrainingEffect")
    )

    anaerobic = safe_float(
        activity.get("anaerobicTrainingEffect")
    )

    average_hr = safe_float(
        activity.get("averageHR")
    )

    duration = safe_float(
        activity.get("duration")
    )

    if anaerobic >= 2.0:
        return True

    if aerobic >= 3.5:
        return True

    if average_hr >= 160 and duration >= 1800:
        return True

    return False


def login_garmin_with_retry():
    token_dir = os.path.expanduser(
        "~/.garminconnect"
    )

    os.makedirs(
        token_dir,
        exist_ok=True
    )

    print("[GARMIN] Login proberen met bestaande token")

    try:
        garmin = Garmin(
            GARMIN_EMAIL,
            GARMIN_WACHTWOORD
        )

        garmin.login(token_dir)

        print("[GARMIN] Login gelukt")

        return garmin

    except Exception as first_error:
        print(
            f"[GARMIN] Eerste login mislukt: "
            f"{first_error}"
        )

        print(
            "[GARMIN] Token/cache verwijderen "
            "en opnieuw proberen"
        )

        if os.path.exists(token_dir):
            shutil.rmtree(token_dir)

        os.makedirs(
            token_dir,
            exist_ok=True
        )

        garmin = Garmin(
            GARMIN_EMAIL,
            GARMIN_WACHTWOORD
        )

        garmin.login(token_dir)

        print(
            "[GARMIN] Login gelukt na verwijderen cache"
        )

        return garmin


def get_sleep_info(garmin):
    attempts = []

    dates_to_try = [
        now_be().date(),
        now_be().date() - timedelta(days=1)
    ]

    for day in dates_to_try:
        day_string = day.isoformat()

        try:
            data = garmin.get_sleep_data(
                day_string
            )

            if not data:
                continue

            score = recursive_find(
                data,
                [
                    "sleepScore",
                    "overallSleepScore",
                    "sleepScoreValue"
                ]
            )

            quality = recursive_find(
                data,
                [
                    "qualityDescription",
                    "sleepScoreFeedback",
                    "sleepQualityType",
                    "sleepQuality"
                ]
            )

            score_int = safe_int(
                score,
                default=-1
            )

            if score_int >= 0:
                return {
                    "status": "beschikbaar",
                    "date": day_string,
                    "score": score_int,
                    "quality": quality
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
        "attempts": attempts
    }


def get_weather_forecast():
    try:
        base_url = (
            "https://api.open-meteo.com/v1/forecast"
        )

        params = {
            "latitude": WEATHER_LAT,
            "longitude": WEATHER_LON,
            "daily": (
                "temperature_2m_max,"
                "temperature_2m_min,"
                "precipitation_probability_max,"
                "wind_speed_10m_max"
            ),
            "timezone": "Europe/Brussels",
            "forecast_days": 5
        }

        url = (
            base_url
            + "?"
            + urllib.parse.urlencode(params)
        )

        with urllib.request.urlopen(
            url,
            timeout=15
        ) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        daily = data.get("daily", {})
        forecast = []

        for index, day in enumerate(
            daily.get("time", [])
        ):
            def value(key):
                values = daily.get(key, [])

                if index < len(values):
                    return values[index]

                return None

            forecast.append({
                "date": day,
                "temp_min_c": value(
                    "temperature_2m_min"
                ),
                "temp_max_c": value(
                    "temperature_2m_max"
                ),
                "rain_probability_pct": value(
                    "precipitation_probability_max"
                ),
                "max_wind_kmh": value(
                    "wind_speed_10m_max"
                )
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


def detect_athlete_metrics(
    garmin,
    activities
):
    result = {
        "ftp": None,
        "ftp_source": None,
        "resting_hr": None,
        "resting_hr_source": None,
        "max_hr": None,
        "max_hr_source": None,
        "power_sessions_detected": 0,
        "weight_kg": GEWICHT
    }

    for offset in range(7):
        day_string = (
            now_be().date()
            - timedelta(days=offset)
        ).isoformat()

        for method_name in (
            "get_user_summary",
            "get_heart_rates"
        ):
            if result["resting_hr"] is not None:
                continue

            if not hasattr(garmin, method_name):
                continue

            try:
                payload = getattr(
                    garmin,
                    method_name
                )(day_string)

                resting = recursive_find(
                    payload,
                    [
                        "restingHeartRate",
                        "restingHR",
                        "restingHr"
                    ]
                )

                if safe_int(resting) > 0:
                    result["resting_hr"] = safe_int(
                        resting
                    )

                    result["resting_hr_source"] = (
                        f"{method_name} {day_string}"
                    )

            except Exception:
                pass

    for method_name in (
        "get_user_profile",
        "get_user_settings"
    ):
        if not hasattr(garmin, method_name):
            continue

        try:
            payload = getattr(
                garmin,
                method_name
            )()

            ftp = recursive_find(
                payload,
                [
                    "functionalThresholdPower",
                    "ftp",
                    "cyclingFtp",
                    "bikeFtp",
                    "thresholdPower"
                ]
            )

            max_hr = recursive_find(
                payload,
                [
                    "maxHeartRate",
                    "maximumHeartRate",
                    "maxHR",
                    "maxHr"
                ]
            )

            if (
                result["ftp"] is None
                and safe_int(ftp) > 0
            ):
                result["ftp"] = safe_int(ftp)
                result["ftp_source"] = method_name

            if (
                result["max_hr"] is None
                and safe_int(max_hr) > 0
            ):
                result["max_hr"] = safe_int(max_hr)
                result["max_hr_source"] = method_name

        except Exception:
            pass

    max_hr_values = []

    for activity in activities:
        max_hr = safe_int(
            activity.get("maxHR")
        )

        if max_hr:
            max_hr_values.append(max_hr)

        type_key = activity.get(
            "activityType",
            {}
        ).get("typeKey")

        discipline = classify_activity_type(
            type_key
        )

        if discipline != "bike":
            continue

        average_power = (
            activity.get("averagePower")
            or activity.get("avgPower")
        )

        normalized_power = (
            activity.get("normalizedPower")
            or activity.get("normPower")
        )

        if (
            average_power is not None
            or normalized_power is not None
        ):
            result[
                "power_sessions_detected"
            ] += 1

    if result["max_hr"] is None:
        plausible = [
            value
            for value in max_hr_values
            if 120 <= value <= 220
        ]

        if plausible:
            result["max_hr"] = max(plausible)
            result["max_hr_source"] = (
                "recente activiteiten"
            )

    power_sessions = result[
        "power_sessions_detected"
    ]

    if power_sessions >= 5:
        result["powerdata"] = "ja"
    elif power_sessions > 0:
        result["powerdata"] = "soms"
    else:
        result["powerdata"] = "nee"

    for key in (
        "ftp",
        "resting_hr",
        "max_hr"
    ):
        if result[key] is None:
            result[key] = "niet gevonden"

    return result


def summarize_activities(activities):
    current = now_be()
    rows = []

    for activity in activities:
        activity_time = parse_garmin_datetime(
            activity.get("startTimeLocal")
        )

        type_key = activity.get(
            "activityType",
            {}
        ).get("typeKey")

        discipline = classify_activity_type(
            type_key
        )

        rows.append({
            "date": (
                activity_time.date().isoformat()
                if activity_time
                else None
            ),
            "datetime": activity_time,
            "week": (
                activity_time.strftime("%G-W%V")
                if activity_time
                else None
            ),
            "name": activity.get(
                "activityName"
            ),
            "discipline": discipline,
            "duration_sec": safe_float(
                activity.get("duration")
            ),
            "distance_km": round(
                safe_float(
                    activity.get("distance")
                ) / 1000,
                1
            ),
            "average_hr": activity.get(
                "averageHR"
            ),
            "max_hr": activity.get("maxHR"),
            "aerobic_te": activity.get(
                "aerobicTrainingEffect"
            ),
            "anaerobic_te": activity.get(
                "anaerobicTrainingEffect"
            ),
            "average_power": (
                activity.get("averagePower")
                or activity.get("avgPower")
            ),
            "normalized_power": (
                activity.get("normalizedPower")
                or activity.get("normPower")
            ),
            "max_power": (
                activity.get("maxPower")
                or activity.get("maxBikePower")
            ),
            "hard": is_hard_session(activity)
        })

    rows.sort(
        key=lambda row: (
            row["datetime"]
            or datetime.min.replace(
                tzinfo=TIMEZONE
            )
        ),
        reverse=True
    )

    def summarize_window(days):
        cutoff = (
            current
            - timedelta(days=days)
        )

        selected = [
            row
            for row in rows
            if (
                row["datetime"]
                and row["datetime"] >= cutoff
            )
        ]

        training_dates = {
            row["date"]
            for row in selected
        }

        by_discipline = {}

        for discipline in (
            "bike",
            "run",
            "swim",
            "strength",
            "other"
        ):
            subset = [
                row
                for row in selected
                if row["discipline"] == discipline
            ]

            by_discipline[discipline] = {
                "sessions": len(subset),
                "duration_h": round(
                    sum(
                        row["duration_sec"]
                        for row in subset
                    ) / 3600,
                    2
                ),
                "distance_km": round(
                    sum(
                        row["distance_km"]
                        for row in subset
                    ),
                    1
                )
            }

        return {
            "total_sessions": len(selected),
            "total_duration_h": round(
                sum(
                    row["duration_sec"]
                    for row in selected
                ) / 3600,
                2
            ),
            "hard_sessions": sum(
                row["hard"]
                for row in selected
            ),
            "training_days": len(
                training_dates
            ),
            "rest_days_estimate": (
                max(
                    0,
                    days - len(training_dates)
                )
                if days == 7
                else None
            ),
            "by_discipline": by_discipline
        }

    cutoff = (
        current
        - timedelta(
            days=ANALYSEPERIODE_DAGEN
        )
    )

    weeks = {}

    for row in rows:
        if not row["datetime"]:
            continue

        if row["datetime"] < cutoff:
            continue

        week_key = row["week"]

        week = weeks.setdefault(
            week_key,
            {
                "week": week_key,
                "total_duration_h": 0.0,
                "bike_duration_h": 0.0,
                "hard_sessions": 0,
                "bike_sessions": 0,
                "power_values": [],
                "max_power_values": []
            }
        )

        week["total_duration_h"] += (
            row["duration_sec"] / 3600
        )

        week["hard_sessions"] += int(
            row["hard"]
        )

        if row["discipline"] == "bike":
            week["bike_sessions"] += 1

            week["bike_duration_h"] += (
                row["duration_sec"] / 3600
            )

            if row["average_power"] is not None:
                week["power_values"].append(
                    safe_float(
                        row["average_power"]
                    )
                )

            if row["max_power"] is not None:
                week[
                    "max_power_values"
                ].append(
                    safe_float(
                        row["max_power"]
                    )
                )

    weekly_trends = []

    for week_key in sorted(weeks):
        week = weeks[week_key]

        power_values = week[
            "power_values"
        ]

        max_power_values = week[
            "max_power_values"
        ]

        weekly_trends.append({
            "week": week_key,
            "total_duration_h": round(
                week["total_duration_h"],
                2
            ),
            "bike_duration_h": round(
                week["bike_duration_h"],
                2
            ),
            "bike_sessions": week[
                "bike_sessions"
            ],
            "hard_sessions": week[
                "hard_sessions"
            ],
            "bike_avg_power": (
                round(
                    sum(power_values)
                    / len(power_values),
                    1
                )
                if power_values
                else None
            ),
            "highest_recorded_max_power": (
                round(
                    max(max_power_values),
                    1
                )
                if max_power_values
                else None
            )
        })

    recent_activities = []

    for row in rows[:10]:
        recent_activities.append({
            "date": row["date"],
            "name": row["name"],
            "discipline": row["discipline"],
            "duration": format_duration(
                row["duration_sec"]
            ),
            "distance_km": row[
                "distance_km"
            ],
            "average_hr": row[
                "average_hr"
            ],
            "aerobic_te": row[
                "aerobic_te"
            ],
            "anaerobic_te": row[
                "anaerobic_te"
            ],
            "average_power": row[
                "average_power"
            ],
            "normalized_power": row[
                "normalized_power"
            ],
            "max_power": row[
                "max_power"
            ],
            "hard": row["hard"]
        })

    return {
        "last_7_days": summarize_window(7),
        "last_28_days": summarize_window(28),
        "condition_evolution": {
            "analysis_period_days": (
                ANALYSEPERIODE_DAGEN
            ),
            "weekly_trends": weekly_trends
        },
        "latest_activity": (
            recent_activities[0]
            if recent_activities
            else None
        ),
        "recent_activities": recent_activities,
        "data_limitations": [
            (
                "Activiteitssamenvattingen tonen "
                "geen betrouwbare tijd in zones "
                "of intervalverloop."
            ),
            (
                "Gemiddeld ritvermogen is niet "
                "geschikt om FTP-, VO2max- of "
                "sprintprogressie op zichzelf te bewijzen."
            ),
            (
                "Techniek, positionering en koersinzicht "
                "zijn niet rechtstreeks uit deze Garmin-"
                "samenvatting af te leiden."
            )
        ],
        "data_quality": {
            "activities_loaded": len(
                activities
            ),
            "activities_with_datetime": sum(
                row["datetime"] is not None
                for row in rows
            ),
            "activities_with_hr": sum(
                row["average_hr"] is not None
                for row in rows
            ),
            "bike_activities_with_power": sum(
                (
                    row["discipline"] == "bike"
                    and row["average_power"]
                    is not None
                )
                for row in rows
            )
        }
    }


def parse_race_date(race):
    try:
        return date.fromisoformat(
            race["date"]
        )

    except (
        KeyError,
        ValueError,
        TypeError
    ):
        return None


def next_races(today):
    result = []

    for race in RACES:
        race_date = parse_race_date(race)

        if race_date and race_date >= today:
            item = dict(race)

            item["days_until"] = (
                race_date - today
            ).days

            result.append(item)

    return sorted(
        result,
        key=lambda item: item["date"]
    )


def previous_races(
    today,
    lookback_days=14
):
    result = []

    for race in RACES:
        race_date = parse_race_date(race)

        if not race_date:
            continue

        days_since = (
            today - race_date
        ).days

        if 0 <= days_since <= lookback_days:
            item = dict(race)
            item["days_since"] = days_since
            result.append(item)

    return sorted(
        result,
        key=lambda item: item["date"],
        reverse=True
    )


def race_calendar_summary():
    season_start = date.fromisoformat(
        SEASON_CONFIG[
            "race_season_start"
        ]
    )

    season_end = date.fromisoformat(
        SEASON_CONFIG[
            "race_season_end"
        ]
    )

    races = []

    for race in RACES:
        race_date = parse_race_date(race)

        if (
            race_date
            and season_start
            <= race_date
            <= season_end
        ):
            races.append(race)

    races = sorted(
        races,
        key=lambda race: race["date"]
    )

    return {
        "planned_races": len(races),
        "planned_a_races": sum(
            race.get("priority") == "A"
            for race in races
        ),
        "target_races": (
            f"{SEASON_CONFIG['target_race_count_min']} "
            f"tot "
            f"{SEASON_CONFIG['target_race_count_max']}"
        ),
        "calendar_complete": (
            SEASON_CONFIG[
                "target_race_count_min"
            ]
            <= len(races)
            <= SEASON_CONFIG[
                "target_race_count_max"
            ]
        ),
        "races": races
    }


def phase_anchor(today):
    anchors = [
        date(2026, 10, 1),
        date(2026, 12, 1),
        date(2027, 2, 1),
        date(2027, 3, 16),
        date(2027, 4, 16),
        date(2027, 5, 1)
    ]

    valid = [
        anchor
        for anchor in anchors
        if anchor <= today
    ]

    if not valid:
        return None

    return max(valid)


def determine_block(today):
    anchor = phase_anchor(today)

    if anchor is None:
        return None

    week = (
        (today - anchor).days // 7
    ) % 4 + 1

    labels = {
        1: "opbouw 1",
        2: "opbouw 2",
        3: "opbouw 3",
        4: "herstelweek"
    }

    if week == 4:
        rule = (
            "Verlaag volume en zware belasting. "
            "Haal geen gemiste trainingen in."
        )
    else:
        rule = (
            "Bouw gecontroleerd op en verhoog "
            "maximaal één hoofdvariabele."
        )

    return {
        "phase_anchor": anchor.isoformat(),
        "week_number": week,
        "week_type": labels[week],
        "rule": rule
    }


def determine_training_phase(
    today,
    upcoming,
    recent
):
    preparation_start = date.fromisoformat(
        SEASON_CONFIG[
            "preparation_start"
        ]
    )

    season_start = date.fromisoformat(
        SEASON_CONFIG[
            "race_season_start"
        ]
    )

    season_end = date.fromisoformat(
        SEASON_CONFIG[
            "race_season_end"
        ]
    )

    next_race = (
        upcoming[0]
        if upcoming
        else None
    )

    last_race = (
        recent[0]
        if recent
        else None
    )

    if today < preparation_start:
        return {
            "phase": "Overgangsperiode",
            "primary_adaptation": (
                "herstel en mentale reset"
            ),
            "goal": (
                "Herstellen en opnieuw zin krijgen "
                "in gestructureerde training."
            ),
            "rules": [
                "Train flexibel en rustig.",
                "Geen vormtest nodig.",
                "Introduceer kracht geleidelijk."
            ]
        }

    if today <= date(2026, 11, 30):
        return {
            "phase": "Basisfase 1",
            "primary_adaptation": (
                "aerobe basis, regelmaat "
                "en algemene kracht"
            ),
            "goal": (
                "Een duurzaam fundament bouwen "
                "zonder vroege wedstrijdvorm na te jagen."
            ),
            "rules": [
                "Meeste fietstijd rustig.",
                "Maximaal één kwaliteitssessie per week.",
                (
                    "Eén of twee krachtsessies "
                    "indien herstelbaar."
                ),
                (
                    "Techniek mag laag belastend "
                    "worden geoefend."
                )
            ]
        }

    if today <= date(2027, 1, 31):
        return {
            "phase": "Basisfase 2",
            "primary_adaptation": (
                "duurzaamheid en musculair "
                "uithoudingsvermogen"
            ),
            "goal": (
                "Langere aerobe belasting combineren "
                "met progressieve sweet spot of tempo."
            ),
            "rules": [
                (
                    "Eén progressieve sweet-spot- "
                    "of temposessie."
                ),
                (
                    "Tweede kwaliteit alleen "
                    "bij goed herstel."
                ),
                "Behoud rustige lange duur.",
                "Behoud krachttraining."
            ]
        }

    if today <= date(2027, 3, 15):
        return {
            "phase": "Gerichte opbouw",
            "primary_adaptation": (
                "drempelvermogen en VO2max"
            ),
            "goal": (
                "Aerobe capaciteit, FTP, "
                "drempelduur en VO2max ontwikkelen."
            ),
            "rules": [
                "Maximaal twee kwaliteitssessies.",
                (
                    "Bij voorkeur minimaal 48 uur "
                    "tussen zware prikkels."
                ),
                (
                    "Een zware groepsrit telt "
                    "als kwaliteitssessie."
                ),
                "Behoud voldoende rustige duur."
            ]
        }

    if today <= date(2027, 4, 15):
        return {
            "phase": "Koersspecifieke opbouw",
            "primary_adaptation": (
                "herhaalde hoge intensiteit "
                "en anaerobe capaciteit"
            ),
            "goal": (
                "Aerobe vorm vertalen naar versnellingen, "
                "herstel tussen inspanningen en "
                "sprint na vermoeidheid."
            ),
            "rules": [
                (
                    "Drempel met een beperkte "
                    "onderhoudsdosis behouden."
                ),
                (
                    "Voeg herhaalde VO2max- of "
                    "anaerobe inspanningen toe."
                ),
                (
                    "Sprint kort, technisch "
                    "en kwalitatief."
                ),
                "Krachttraining gaat naar onderhoud."
            ]
        }

    if today < season_start:
        return {
            "phase": "Wedstrijdvoorbereiding",
            "primary_adaptation": (
                "koersscherpte en vaardigheid"
            ),
            "goal": (
                "Fysieke kwaliteiten combineren met "
                "positionering, bochten, tempowissels "
                "en sprinttiming."
            ),
            "rules": [
                (
                    "Gebruik een koerssimulatie of snelle "
                    "groepsrit als kwaliteitssessie."
                ),
                "Geen taper zonder A-wedstrijd.",
                "Vermoeidheid niet opstapelen.",
                (
                    "Techniek en positionering "
                    "bewust oefenen."
                )
            ]
        }

    if today <= season_end:
        if (
            last_race
            and last_race["days_since"] <= 2
        ):
            return {
                "phase": "Herstel na wedstrijd",
                "primary_adaptation": "herstel",
                "goal": (
                    "Wedstrijdvermoeidheid laten zakken "
                    "en de volgende prikkel correct timen."
                ),
                "rules": [
                    "Rust of zeer licht fietsen.",
                    "Geen gemiste kilometers inhalen.",
                    (
                        "Laat feedback en herstel "
                        "de hervatting bepalen."
                    )
                ]
            }

        if (
            next_race
            and next_race["days_until"] == 0
        ):
            return {
                "phase": "Wedstrijddag",
                "primary_adaptation": (
                    "wedstrijdprestatie"
                ),
                "goal": (
                    "Fris en voorbereid starten."
                ),
                "rules": [
                    "Wedstrijd is de hoofdtraining.",
                    "Gebruik een functionele warming-up.",
                    (
                        "Focus op veilige positionering "
                        "en beslismomenten."
                    )
                ]
            }

        if (
            next_race
            and next_race.get("priority") == "A"
            and next_race["days_until"] <= 5
        ):
            return {
                "phase": "Taper richting A-wedstrijd",
                "primary_adaptation": (
                    "frisheid met behoud van scherpte"
                ),
                "goal": (
                    "Vermoeidheid verlagen zonder "
                    "wedstrijdscherpte te verliezen."
                ),
                "rules": [
                    "Verlaag het volume.",
                    "Behoud korte openers.",
                    (
                        "Geen zware drempel-, VO2max- "
                        "of krachttraining."
                    )
                ]
            }

        return {
            "phase": "Wedstrijdperiode",
            "primary_adaptation": (
                "vorm onderhouden en toepassen"
            ),
            "goal": (
                "Wedstrijden, herstel en gerichte "
                "onderhoudstraining in balans brengen."
            ),
            "rules": [
                (
                    "Een wedstrijd telt als "
                    "kwaliteitssessie."
                ),
                (
                    "Plan geen twee zware intervals "
                    "plus een wedstrijd."
                ),
                (
                    "Gebruik wedstrijdarme blokken "
                    "voor gerichte ontwikkeling."
                ),
                (
                    "Plan maximaal twee "
                    "wedstrijdweekends na elkaar."
                )
            ]
        }

    return {
        "phase": "Overgang na seizoen",
        "primary_adaptation": (
            "herstel en evaluatie"
        ),
        "goal": (
            "Herstellen, evalueren en pas daarna "
            "een nieuwe opbouw starten."
        ),
        "rules": [
            "Neem rustige of volledig vrije dagen.",
            (
                "Evalueer het volledige "
                "prestatieprofiel."
            ),
            (
                "Start niet onmiddellijk "
                "een nieuw zwaar blok."
            )
        ]
    }


def determine_recovery_risk(
    summary,
    sleep,
    feedback
):
    risk_score = 0
    reasons = []

    feedback_text = (
        feedback or ""
    ).lower()

    warning_words = (
        "pijn",
        "blessure",
        "ziek",
        "koorts",
        "oververmoeid",
        "uitgeput",
        "zeer moe",
        "zware benen",
        "lege benen",
        "geen energie"
    )

    if any(
        word in feedback_text
        for word in warning_words
    ):
        risk_score += 3

        reasons.append(
            "De subjectieve feedback bevat "
            "een duidelijk waarschuwingssignaal."
        )

    sleep_score = sleep.get("score")

    if sleep_score is None:
        risk_score += 1

        reasons.append(
            "De slaapscore ontbreekt. "
            "Herstel wordt daarom niet positief verondersteld."
        )

    elif sleep_score < 60:
        risk_score += 3

        reasons.append(
            f"De slaapscore is zeer laag: "
            f"{sleep_score}/100."
        )

    elif sleep_score < 70:
        risk_score += 2

        reasons.append(
            f"De slaapscore is laag: "
            f"{sleep_score}/100."
        )

    elif sleep_score < 78:
        risk_score += 1

        reasons.append(
            f"De slaapscore is matig: "
            f"{sleep_score}/100."
        )

    else:
        reasons.append(
            f"De slaapscore is bruikbaar tot goed: "
            f"{sleep_score}/100."
        )

    last_7_days = summary[
        "last_7_days"
    ]

    hard_sessions = last_7_days[
        "hard_sessions"
    ]

    if hard_sessions >= 3:
        risk_score += 2

        reasons.append(
            f"Er waren {hard_sessions} intensieve "
            "sessies in zeven dagen."
        )

    elif hard_sessions == 2:
        risk_score += 1

        reasons.append(
            "Er waren twee intensieve "
            "sessies in zeven dagen."
        )

    rest_days = last_7_days[
        "rest_days_estimate"
    ]

    if (
        rest_days is not None
        and rest_days <= 1
    ):
        risk_score += 1

        reasons.append(
            "Er waren weinig rustdagen "
            "in de laatste zeven dagen."
        )

    total_duration = last_7_days[
        "total_duration_h"
    ]

    if total_duration >= 10:
        risk_score += 2

        reasons.append(
            f"Het volume van de laatste zeven dagen "
            f"is hoog: {total_duration} uur."
        )

    elif total_duration >= 7:
        risk_score += 1

        reasons.append(
            f"Het volume van de laatste zeven dagen "
            f"is matig tot hoog: {total_duration} uur."
        )

    if risk_score >= 5:
        level = "hoog"

        boundaries = [
            "rust of maximaal een zeer lichte herstelrit",
            "geen intervals",
            "geen benchmarktest",
            "geen lange duurtraining"
        ]

    elif risk_score >= 3:
        level = "medium"

        boundaries = [
            "volume niet verhogen",
            (
                "hoogstens een korte kwaliteitssessie "
                "als de benen goed voelen"
            ),
            "geen benchmarktest",
            "geen diepe intervals"
        ]

    else:
        level = "laag"

        boundaries = [
            "fasegebonden training toegestaan",
            (
                "maximaal twee kwaliteitssessies "
                "per week"
            ),
            (
                "bij voorkeur minimaal 48 uur "
                "tussen zware prikkels"
            )
        ]

    return {
        "level": level,
        "score": risk_score,
        "reasons": reasons,
        "allowed_training_boundaries": boundaries
    }


def build_context(
    summary,
    sleep,
    weather,
    phase,
    races,
    recent,
    recovery,
    metrics
):
    return {
        "today": now_be().date().isoformat(),
        "weekday": now_be().strftime("%A"),
        "mode": MODUS,
        "athlete_profile": ATHLETE_PROFILE,
        "season_config": SEASON_CONFIG,
        "current_training_phase": phase,
        "training_block": determine_block(
            now_be().date()
        ),
        "race_calendar": race_calendar_summary(),
        "upcoming_races": races,
        "recent_races": recent,
        "recovery_risk": recovery,
        "sleep": sleep,
        "weather": weather,
        "garmin_summary": summary,
        "athlete_metrics": metrics,
        "user_feedback": USER_FEEDBACK,
        "extra_context": EXTRA_CONTEXT,
        "hard_constraints": [
            (
                "Optimaliseer allround wielerprestatie. "
                "FTP is belangrijk maar nooit het enige doel."
            ),
            (
                "Gezondheid, continuïteit en herstelbaarheid "
                "gaan voor een losse zware training."
            ),
            (
                "Kies één primaire adaptatie per fase en week. "
                "Onderhoud andere kwaliteiten met de "
                "kleinst effectieve dosis."
            ),
            (
                "Elke kwaliteitstraining moet in een "
                "herkenbare progressie passen."
            ),
            (
                "Verhoog per stap maximaal één hoofdvariabele: "
                "duur, herhalingen, vermogen of totale omvang."
            ),
            (
                "Maximaal twee kwaliteitssessies per week. "
                "Een zware groepsrit of wedstrijd telt mee."
            ),
            (
                "Behoud voldoende rustige duur en minstens "
                "één rustdag of zeer lichte dag per week."
            ),
            (
                "Gebruik meestal drie opbouwweken en één "
                "herstelweek, maar hersteldata gaan voor."
            ),
            (
                "Plan bij voorkeur minimaal 48 uur "
                "tussen zware prikkels."
            ),
            (
                "Geen dubbele trainingsdagen en maximaal "
                "één hoofdtraining per dag."
            ),
            (
                "Krachttraining is opbouwend in de basisfase "
                "en onderhoudend richting wedstrijden."
            ),
            (
                "Techniek, positionering en bochtenwerk mogen "
                "als laag-belastende vaardigheidsfocus "
                "worden opgenomen."
            ),
            (
                "Geen benchmarktest bij medium of hoog "
                "herstelrisico, pijn, ziekte of duidelijke "
                "vermoeidheid."
            ),
            (
                "Gebruik voor trendvergelijking hetzelfde "
                "testprotocol en dezelfde vermogensbron. "
                "Test hoogstens om de zes tot acht weken."
            ),
            (
                "Verzin geen FTP, zones, HRV, trainingsbelasting, "
                "wedstrijd of prestatieverbetering."
            ),
            (
                "Gemiddeld ritvermogen is geen bewijs van "
                "FTP-stijging of betere koersvorm."
            ),
            (
                "Beoordeel sprint, duurzaamheid en herhaalde "
                "inspanningen alleen wanneer de data "
                "dit ondersteunen."
            ),
            (
                "Praktische voeding en hydratatie mogen worden "
                "benoemd, maar zonder medische of absolute claims."
            ),
            (
                "Geef duidelijk aan wat feit uit de data is "
                "en wat een coachinschatting is."
            )
        ]
    }


def build_prompt(context):
    structures = {
        "dagadvies": """
COACH TAKE

TYPE DAG

HERSTELSTATUS

LAATSTE WORKOUT

VANDAAG
- Exacte training of rust
- Duur
- Intensiteit
- Uitvoering
- Afbreekcriteria

TRAININGSDOEL
Welke capaciteit of vaardigheid wordt ontwikkeld?

WAAROM NU
Leg de link met:
- huidige fase
- huidig trainingsblok
- recente belasting
- volgende wedstrijd

MORGEN

NIET DOEN

PROGRESSIE
Wat wordt opgebouwd, onderhouden of bewust niet geprikkeld?

FEITEN EN COACHINSCHATTING
Maak kort het onderscheid.
""",

        "week_schema": """
COACH TAKE

HERSTELSTATUS

WEEKDOEL

PRIMAIRE ADAPTATIE VAN DE WEEK

ONDERHOUDSDOELEN

WEEKSCHEMA
Geef per dag:
- maximaal één hoofdtraining
- duur
- intensiteit
- concrete uitvoering
- trainingsdoel

BELASTINGSLOGICA
Leg uit waar de zware dagen, rustige dagen en herstelmomenten staan.

PROGRESSIE TEGENOVER DE VORIGE VERGELIJKBARE WEEK

VAARDIGHEID EN KOERSSPECIFIEKE FOCUS

NIET DOEN

FEITEN EN COACHINSCHATTING
""",

        "race_readiness": """
COACH TAKE

READINESS
Kies:
- goed
- oké met marge
- voorzichtig

Gebruik geen percentage.

HERSTELSTATUS

LAATSTE 72 UUR

WARMING-UP

KOERSFOCUS
Bespreek:
- positionering
- bochten
- inspanningsverdeling
- beslismomenten

FYSIEKE FOCUS
Welke capaciteit moet gebruikt worden en wat moet niet meer opgebouwd worden?

HERSTEL NA DE WEDSTRIJD

NIET DOEN
""",

        "conditie_evolutie": """
SAMENVATTING

TRAININGSCONTINUÏTEIT EN BELASTINGSTREND

AEROBE BASIS EN DUURZAAMHEID

FTP EN DREMPEL
Maak onderscheid tussen:
- gemeten waarde
- indirecte signalen
- ontbrekende data

VO2MAX EN HERHAALDE HOGE INTENSITEIT

ANAEROBE CAPACITEIT EN SPRINT

HERSTELBALANS

KRACHT EN AANVULLENDE SPORTEN

VAARDIGHEDEN EN KOERSSPECIFICITEIT
Beoordeel dit alleen als de data het werkelijk tonen.

WAT BEHOUDEN

WAT AANPASSEN

CONCLUSIE VOOR DE KOMENDE TWEE WEKEN
""",

        "seizoen_plan": """
COACH TAKE

HUIDIGE SITUATIE

PRESTATIEPROFIEL
Bespreek:
- ontwikkeldoelen
- beschikbare data
- databeperkingen

SEIZOENSOPBOUW PER FASE

DOEL PER CAPACITEIT
Bespreek:
- aerobe basis
- FTP
- drempelduur
- VO2max
- anaerobe capaciteit
- sprint
- duurzaamheid
- kracht
- techniek

WEDSTRIJDPLANNING
Gebruik alleen werkelijk ingevoerde wedstrijden.

HERSTEL- EN BENCHMARKMOMENTEN

KOMENDE VIER WEKEN

BELANGRIJKSTE AANPASSING
"""
    }

    structure = structures.get(
        MODUS,
        structures["dagadvies"]
    )

    return f"""
Je bent een nuchtere, ervaren wielercoach voor criterium- en wegwielrennen.

Schrijf kort, menselijk, direct en concreet in het Nederlands.

Het doel is niet een zo hoog mogelijke FTP op papier, maar de best mogelijke allround wedstrijdprestatie van mei tot midden september 2027.

FTP is een belangrijke bouwsteen naast:
- aerobe duurzaamheid
- drempelduur
- VO2max
- herhaalde inspanningen
- anaerobe capaciteit
- sprint
- kracht
- techniek
- herstel
- koersinzicht

Coachregels:

- Volg altijd de recovery boundaries en hard constraints uit de context.
- Kies per fase en per week één primaire adaptatie.
- Onderhoud andere kwaliteiten met de kleinst effectieve dosis.
- Gebruik rustige duur, tempo, sweet spot, drempel, VO2max, anaerobe prikkels, sprint, kracht en techniek alleen wanneer ze bij de fase en herstelstatus passen.
- Benoem bij iedere training het doel, de plaats in het blok en de beoogde progressie.
- Verhoog per progressiestap maximaal één hoofdvariabele.
- Meer training is niet automatisch beter.
- Een zware groepsrit of wedstrijd vervangt een kwaliteitssessie en komt er niet bovenop.
- Gebruik herstel als combinatie van slaap, recente belasting en subjectieve feedback.
- Een losse goede of slechte waarde beslist nooit alleen.
- Als interval-, lap- of tijdreeksdata ontbreken, claim dan geen bewezen progressie in FTP, VO2max, sprint of duurzaamheid.
- Gemiddeld vermogen van een volledige rit is geen bewijs van wedstrijdvorm.
- Adviseer een benchmark alleen bij laag herstelrisico, na een passend trainingsblok en wanneer een vergelijkbare test minstens zes weken geleden was.
- Als de testhistoriek ontbreekt, zeg dat expliciet.
- Maak duidelijk onderscheid tussen feiten uit de data en coachinschattingen.
- Vermijd clichés, heroische taal, medische claims en verzonnen cijfers.

OUTPUTSTRUCTUUR:

{structure}

Context in JSON:

{json.dumps(context, ensure_ascii=False, indent=2)}
"""


def call_gemini(prompt):
    require_env(
        "GEMINI_API_KEY",
        GEMINI_API_KEY
    )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-1.5-flash"
    ]

    last_error = None

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                print(
                    f"[GEMINI] Model {model_name}, "
                    f"poging {attempt + 1}/3"
                )

                response = (
                    client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )
                )

                if (
                    response.text
                    and response.text.strip()
                ):
                    return response.text.strip()

            except Exception as error:
                last_error = error
                error_text = str(error).lower()

                temporary_error = any(
                    token in error_text
                    for token in (
                        "503",
                        "unavailable",
                        "rate",
                        "429",
                        "resource_exhausted"
                    )
                )

                if temporary_error:
                    time.sleep(10)
                else:
                    raise

    raise RuntimeError(
        "Gemini gaf geen bruikbare output. "
        f"Laatste fout: {last_error}"
    )


def subject_for_mode(context):
    if MODUS == "seizoen_plan":
        return (
            "Wielercoach - seizoensplanning "
            "en wielervorm 2026-2027"
        )

    races = context.get(
        "upcoming_races",
        []
    )

    if races:
        target = (
            f"{races[0]['name']} over "
            f"{races[0]['days_until']} dagen"
        )
    else:
        target = context[
            "current_training_phase"
        ]["phase"]

    labels = {
        "week_schema": "weekschema",
        "race_readiness": "race readiness",
        "conditie_evolutie": "conditie-evolutie",
        "dagadvies": "dagadvies"
    }

    label = labels.get(
        MODUS,
        "dagadvies"
    )

    return (
        f"Wielercoach - {label} "
        f"richting {target}"
    )


def send_email(subject, body):
    require_env(
        "GMAIL_ADRES",
        GMAIL_ADRES
    )

    require_env(
        "GMAIL_APP_WACHTWOORD",
        GMAIL_APP_WACHTWOORD
    )

    require_env(
        "EMAIL_ONTVANGER",
        EMAIL_ONTVANGER
    )

    sender = GMAIL_ADRES.strip()
    recipient = EMAIL_ONTVANGER.strip()

    if "@" not in sender:
        raise RuntimeError(
            "GMAIL_ADRES lijkt geen geldig e-mailadres."
        )

    if "@" not in recipient:
        raise RuntimeError(
            "EMAIL_ONTVANGER lijkt geen geldig e-mailadres."
        )

    msg = MIMEMultipart()

    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject

    msg.attach(
        MIMEText(
            body,
            "plain",
            "utf-8"
        )
    )

    with smtplib.SMTP(
        "smtp.gmail.com",
        587,
        timeout=30
    ) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()

        server.login(
            sender,
            GMAIL_APP_WACHTWOORD
        )

        refused = server.sendmail(
            sender,
            [recipient],
            msg.as_string()
        )

        if refused:
            raise RuntimeError(
                "Gmail SMTP heeft de ontvanger "
                f"geweigerd: {refused}"
            )


def main():
    require_env(
        "GARMIN_EMAIL",
        GARMIN_EMAIL
    )

    require_env(
        "GARMIN_WACHTWOORD",
        GARMIN_WACHTWOORD
    )

    require_env(
        "GEMINI_API_KEY",
        GEMINI_API_KEY
    )

    print("[STAP 1] Inloggen bij Garmin")

    garmin = login_garmin_with_retry()

    print("[STAP 2] Activiteiten ophalen")

    if MODUS in {
        "conditie_evolutie",
        "seizoen_plan"
    }:
        activities_to_fetch = 200
    else:
        activities_to_fetch = 80

    activities = garmin.get_activities(
        0,
        activities_to_fetch
    )

    if not activities:
        raise RuntimeError(
            "Geen Garmin activiteiten gevonden."
        )

    print("[STAP 3] Slaap ophalen")

    sleep = get_sleep_info(garmin)

    print("[STAP 4] Weer ophalen")

    weather = get_weather_forecast()

    print("[STAP 5] Atleetmetrics ophalen")

    metrics = detect_athlete_metrics(
        garmin,
        activities
    )

    print("[STAP 6] Activiteiten analyseren")

    summary = summarize_activities(
        activities
    )

    today = now_be().date()

    races = next_races(today)

    recent_races = previous_races(
        today
    )

    phase = determine_training_phase(
        today,
        races,
        recent_races
    )

    recovery = determine_recovery_risk(
        summary,
        sleep,
        USER_FEEDBACK
    )

    context = build_context(
        summary=summary,
        sleep=sleep,
        weather=weather,
        phase=phase,
        races=races,
        recent=recent_races,
        recovery=recovery,
        metrics=metrics
    )

    print("[STAP 7] Prompt bouwen")

    prompt = build_prompt(context)

    print("[STAP 8] Coachadvies genereren")

    ai_text = call_gemini(prompt)

    footer = f"""

--
KORTE DATA-CHECK

Datum: {today.isoformat()}
Fase: {phase["phase"]}
Primaire adaptatie: {phase["primary_adaptation"]}
Blok: {context.get("training_block")}

Slaapstatus: {sleep.get("status")}
Slaapscore: {sleep.get("score")}

Recovery risk: {recovery.get("level")} ({recovery.get("score")})

FTP automatisch: {metrics.get("ftp")} ({metrics.get("ftp_source")})
Rusthartslag automatisch: {metrics.get("resting_hr")} ({metrics.get("resting_hr_source")})
Max HR automatisch: {metrics.get("max_hr")} ({metrics.get("max_hr_source")})

Power-sessies gevonden: {metrics.get("power_sessions_detected")}
Analyseperiode: {ANALYSEPERIODE_DAGEN} dagen
Activiteiten geladen: {summary["data_quality"]["activities_loaded"]}
Wedstrijden ingevoerd: {context["race_calendar"]["planned_races"]}
"""

    final_text = (
        ai_text.strip()
        + footer
    )

    print("[STAP 9] Mail verzenden")

    subject = subject_for_mode(
        context
    )

    send_email(
        subject,
        final_text
    )

    print(
        "[SUCCES] Coachadvies verzonden."
    )


if __name__ == "__main__":
    try:
        main()

    except Exception:
        print("")
        print("CRITICAL ERROR")
        traceback.print_exc()
        print("")
        sys.exit(1)
