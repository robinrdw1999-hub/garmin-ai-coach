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

USER_FEEDBACK = (
    os.environ.get("USER_FEEDBACK")
    or "Geen actuele subjectieve feedback opgegeven."
)

EXTRA_CONTEXT = os.environ.get("EXTRA_CONTEXT") or ""

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

    "starting_level": (
        "De atleet kan wielerwedstrijden uitrijden, "
        "maar rijdt momenteel nog niet structureel mee voor de prijzen."
    ),

    "main_goal": (
        "Van wedstrijden uitrijden doorgroeien naar competitief "
        "meedoen voor de prijzen in criterium- en wegwedstrijden."
    ),

    "goal_type": (
        "Ambitieus prestatiedoel. Geen gegarandeerde uitkomst."
    ),

    "target_race_count_min": 12,
    "target_race_count_max": 16,
    "max_consecutive_race_weekends": 2,
    "target_a_races_min": 3,
    "target_a_races_max": 4,

    "discipline": "criterium- en wegwedstrijden",

    "development_goals": [
        "gezond en consistent kunnen trainen",
        "aerobe basis en duurzaamheid verbeteren",
        "FTP en tijd tot uitputting rond drempel verbeteren",
        "VO2max verhogen",
        "herhaalde inspanningen boven drempel beter verwerken",
        "anaerobe capaciteit ontwikkelen",
        "acceleratievermogen verbeteren",
        "sprintvermogen en sprint na vermoeidheid verbeteren",
        "vermogen laat in een wedstrijd beter behouden",
        "bochtentechniek en positionering verbeteren",
        "koersinzicht en inspanningsverdeling ontwikkelen",
        "frisheid rond prioritaire wedstrijden bewaken"
    ],

    "success_indicators": [
        "langer in het relevante wedstrijddeel van het peloton blijven",
        "minder terrein verliezen na herhaalde acceleraties",
        "later in de wedstrijd nog een hoge inspanning kunnen leveren",
        "beter gepositioneerd aan de finale beginnen",
        "regelmatig de finale van wedstrijden bereiken",
        "in geselecteerde wedstrijden competitief voor een uitslag rijden"
    ]
}


ATHLETE_PROFILE = {
    "weight_kg": GEWICHT,
    "primary_sport": "wielrennen",

    "main_objective": (
        "Van wedstrijden kunnen uitrijden doorgroeien naar "
        "competitief meedoen voor de prijzen in criterium- "
        "en wegwedstrijden. FTP is belangrijk, maar is "
        "slechts één bouwsteen."
    ),

    "performance_hierarchy": [
        "gezondheid, continuïteit en herstelbaarheid",
        "aerobe basis en duurzaamheid",
        "FTP en drempelduur",
        "VO2max en herhaalde hoge intensiteit",
        "anaerobe capaciteit en acceleratievermogen",
        "sprintvermogen en sprint na vermoeidheid",
        "techniek, positionering en koersvaardigheid",
        "wedstrijdspecifieke frisheid"
    ],

    "other_sports": (
        "Andere sporten zijn alleen aanvullend. Ze mogen "
        "fietskwaliteit, herstel en trainingscontinuïteit "
        "niet hinderen."
    ),

    "max_main_sessions_per_day": 1,
    "max_quality_sessions_per_week": 2,

    "default_block_structure": (
        "Meestal drie progressieve opbouwweken en één "
        "herstelweek. Hersteldata en subjectieve feedback "
        "gaan altijd voor de kalender."
    ),

    "benchmark_frequency": (
        "Hoogstens om de zes tot acht weken, met hetzelfde "
        "protocol en dezelfde vermogensbron."
    ),

    "tone": (
        "Nuchter, menselijk, direct, kritisch en licht coachend."
    ),

    "strength_training": {
        "purpose": [
            "maximale kracht en neuromusculaire capaciteit ontwikkelen",
            "acceleratie en sprintvermogen ondersteunen",
            "krachtverlies later in wedstrijden beperken",
            "algemene robuustheid en belastbaarheid ondersteunen"
        ],

        "base_phase_frequency": (
            "Meestal twee niet-opeenvolgende krachtsessies per week, "
            "indien dit herstelbaar is."
        ),

        "build_phase_frequency": (
            "Meestal één onderhoudssessie per week. Een tweede sessie "
            "is alleen mogelijk bij lage fietsbelasting en goed herstel."
        ),

        "race_phase_frequency": (
            "Eén korte onderhoudssessie per zeven tot tien dagen, "
            "afhankelijk van wedstrijdkalender en herstel."
        ),

        "exercise_families": [
            "squat- of split-squatpatroon",
            "heupdominant patroon zoals deadlift, Romanian deadlift of hip hinge",
            "unilaterale beenkracht zoals split squat of step-up",
            "kuitkracht",
            "rompstabiliteit en anti-rotatie",
            "duw- en trekbewegingen voor algemene balans"
        ],

        "rules": [
            "techniek gaat altijd voor belasting",
            "geen maximale herhalingstest zonder competente begeleiding",
            "geen trainen tot volledig spierfalen",
            "krachttraining mag een belangrijke fietstraining niet ondermijnen",
            "geen zware beentraining binnen 48 uur voor een prioritaire wedstrijd",
            "verminder eerst het aantal sets voordat oefeningen volledig verdwijnen",
            "verwachte spierpijn moet beperkt blijven"
        ]
    }
}


MONTH_PLAN_CONFIG = {
    "default_weeks": 4,

    "required_sections": [
        "doel van de maand",
        "primaire adaptatie",
        "onderhoudsdoelen",
        "fietsaccent per week",
        "krachtaccent per week",
        "herstelaccent",
        "benchmark of evaluatie",
        "voorwaarden voor bijsturing"
    ],

    "planning_rules": [
        (
            "Gebruik de maand die in extra_context wordt genoemd. "
            "Als geen maand wordt genoemd, gebruik de huidige kalendermaand."
        ),
        (
            "Een maandplan is een kader per week en geen volledig "
            "dichtgetimmerd dagschema."
        ),
        (
            "Als de maand vijf gedeeltelijke of volledige trainingsweken "
            "bevat, voeg dan week 5 toe."
        ),
        (
            "De zwaarste fiets- en krachtsessie mogen niet automatisch "
            "op opeenvolgende dagen staan."
        ),
        (
            "Plan per maand één primaire adaptatie en maximaal twee "
            "duidelijke onderhoudsdoelen."
        ),
        (
            "Een herstelweek verlaagt zowel fietsbelasting als krachtvolume."
        ),
        (
            "Bij medium of hoog herstelrisico wordt het plan afgeschaald."
        )
    ]
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
    # },
    #
    # {
    #     "date": "2027-06-20",
    #     "name": "Naam prioritaire wedstrijd",
    #     "type": "cycling_race",
    #     "priority": "A",
    #     "note": "Prioritaire wedstrijd met gerichte taper."
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
            sleep_data = garmin.get_sleep_data(
                day_string
            )

            if not sleep_data:
                continue

            score = recursive_find(
                sleep_data,
                [
                    "sleepScore",
                    "overallSleepScore",
                    "sleepScoreValue"
                ]
            )

            quality = recursive_find(
                sleep_data,
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
            def get_daily_value(key):
                values = daily.get(key, [])

                if index < len(values):
                    return values[index]

                return None

            forecast.append({
                "date": day,
                "temp_min_c": get_daily_value(
                    "temperature_2m_min"
                ),
                "temp_max_c": get_daily_value(
                    "temperature_2m_max"
                ),
                "rain_probability_pct": get_daily_value(
                    "precipitation_probability_max"
                ),
                "max_wind_kmh": get_daily_value(
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
        plausible_values = [
            value
            for value in max_hr_values
            if 120 <= value <= 220
        ]

        if plausible_values:
            result["max_hr"] = max(
                plausible_values
            )

            result["max_hr_source"] = (
                "hoogste plausibele waarde "
                "uit recente activiteiten"
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
    current_time = now_be()
    structured = []

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

        structured.append({
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

    structured.sort(
        key=lambda item: (
            item["datetime"]
            or datetime.min.replace(
                tzinfo=TIMEZONE
            )
        ),
        reverse=True
    )

    def summarize_window(days):
        cutoff = (
            current_time
            - timedelta(days=days)
        )

        selected = [
            item
            for item in structured
            if (
                item["datetime"]
                and item["datetime"] >= cutoff
            )
        ]

        training_dates = {
            item["date"]
            for item in selected
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
                item
                for item in selected
                if item["discipline"] == discipline
            ]

            by_discipline[discipline] = {
                "sessions": len(subset),
                "duration_h": round(
                    sum(
                        item["duration_sec"]
                        for item in subset
                    ) / 3600,
                    2
                ),
                "distance_km": round(
                    sum(
                        item["distance_km"]
                        for item in subset
                    ),
                    1
                )
            }

        return {
            "total_sessions": len(selected),
            "total_duration_h": round(
                sum(
                    item["duration_sec"]
                    for item in selected
                ) / 3600,
                2
            ),
            "hard_sessions": sum(
                item["hard"]
                for item in selected
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

    analysis_cutoff = (
        current_time
        - timedelta(
            days=ANALYSEPERIODE_DAGEN
        )
    )

    weeks = {}

    for item in structured:
        if not item["datetime"]:
            continue

        if item["datetime"] < analysis_cutoff:
            continue

        week_key = item["week"]

        week = weeks.setdefault(
            week_key,
            {
                "week": week_key,
                "total_duration_h": 0.0,
                "bike_duration_h": 0.0,
                "hard_sessions": 0,
                "bike_sessions": 0,
                "strength_sessions": 0,
                "power_values": [],
                "max_power_values": []
            }
        )

        week["total_duration_h"] += (
            item["duration_sec"] / 3600
        )

        week["hard_sessions"] += int(
            item["hard"]
        )

        if item["discipline"] == "bike":
            week["bike_sessions"] += 1

            week["bike_duration_h"] += (
                item["duration_sec"] / 3600
            )

            if item["average_power"] is not None:
                week["power_values"].append(
                    safe_float(
                        item["average_power"]
                    )
                )

            if item["max_power"] is not None:
                week[
                    "max_power_values"
                ].append(
                    safe_float(
                        item["max_power"]
                    )
                )

        if item["discipline"] == "strength":
            week["strength_sessions"] += 1

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
            "strength_sessions": week[
                "strength_sessions"
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

    for item in structured[:10]:
        recent_activities.append({
            "date": item["date"],
            "name": item["name"],
            "discipline": item["discipline"],
            "duration": format_duration(
                item["duration_sec"]
            ),
            "distance_km": item[
                "distance_km"
            ],
            "average_hr": item[
                "average_hr"
            ],
            "aerobic_te": item[
                "aerobic_te"
            ],
            "anaerobic_te": item[
                "anaerobic_te"
            ],
            "average_power": item[
                "average_power"
            ],
            "normalized_power": item[
                "normalized_power"
            ],
            "max_power": item[
                "max_power"
            ],
            "hard": item["hard"]
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

        "recent_activities": (
            recent_activities
        ),

        "data_limitations": [
            (
                "Activiteitssamenvattingen tonen "
                "geen betrouwbare tijd in vermogenszones "
                "of het volledige intervalverloop."
            ),
            (
                "Gemiddeld ritvermogen is niet geschikt "
                "om FTP-, VO2max- of sprintprogressie "
                "op zichzelf te bewijzen."
            ),
            (
                "Een geregistreerd maximaal vermogen "
                "kan door meetfouten of een zeer korte piek "
                "worden beïnvloed."
            ),
            (
                "Techniek, positionering en koersinzicht "
                "zijn niet rechtstreeks uit Garmin-"
                "activiteitssamenvattingen af te leiden."
            ),
            (
                "Krachttraining wordt alleen herkend wanneer "
                "Garmin het activiteitstype correct registreert."
            )
        ],

        "data_quality": {
            "activities_loaded": len(
                activities
            ),
            "activities_with_datetime": sum(
                item["datetime"] is not None
                for item in structured
            ),
            "activities_with_hr": sum(
                item["average_hr"] is not None
                for item in structured
            ),
            "bike_activities_with_power": sum(
                (
                    item["discipline"] == "bike"
                    and item["average_power"]
                    is not None
                )
                for item in structured
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

        "planned_b_races": sum(
            race.get("priority") == "B"
            for race in races
        ),

        "planned_c_races": sum(
            race.get("priority") == "C"
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

    valid_anchors = [
        anchor
        for anchor in anchors
        if anchor <= today
    ]

    if not valid_anchors:
        return None

    return max(valid_anchors)


def determine_block(today):
    anchor = phase_anchor(today)

    if anchor is None:
        return None

    week_number = (
        (today - anchor).days // 7
    ) % 4 + 1

    labels = {
        1: "opbouwweek 1",
        2: "opbouwweek 2",
        3: "opbouwweek 3",
        4: "herstel- of consolidatieweek"
    }

    if week_number == 4:
        rule = (
            "Verlaag fietsvolume en krachtvolume. "
            "Behoud alleen beperkte intensiteit indien "
            "het herstelrisico laag is."
        )
    else:
        rule = (
            "Bouw gecontroleerd op en verhoog maximaal "
            "één hoofdvariabele."
        )

    return {
        "phase_anchor": anchor.isoformat(),
        "week_number": week_number,
        "week_type": labels[week_number],
        "rule": rule
    }


def determine_training_phase(
    today,
    upcoming_races,
    recent_races
):
    preparation_start = date.fromisoformat(
        SEASON_CONFIG[
            "preparation_start"
        ]
    )

    race_season_start = date.fromisoformat(
        SEASON_CONFIG[
            "race_season_start"
        ]
    )

    race_season_end = date.fromisoformat(
        SEASON_CONFIG[
            "race_season_end"
        ]
    )

    next_race = (
        upcoming_races[0]
        if upcoming_races
        else None
    )

    last_race = (
        recent_races[0]
        if recent_races
        else None
    )

    if today < preparation_start:
        return {
            "phase": "Overgangsperiode",
            "primary_adaptation": (
                "herstel en mentale reset"
            ),
            "goal": (
                "Het vorige seizoen afsluiten en "
                "hersteld aan de voorbereiding beginnen."
            ),
            "bike_focus": (
                "Flexibel, rustig en zonder "
                "wedstrijdgerichte belasting."
            ),
            "strength_focus": (
                "Mobiliteit en gecontroleerde gewenning. "
                "Nog geen zware krachtopbouw."
            ),
            "rules": [
                "Train flexibel en overwegend rustig.",
                "Geen vormtest nodig.",
                "Geen vroege wedstrijdvorm nastreven.",
                "Introduceer krachttraining geleidelijk."
            ]
        }

    if today <= date(2026, 11, 30):
        return {
            "phase": "Basisfase 1",
            "primary_adaptation": (
                "aerobe basis, regelmaat en algemene kracht"
            ),
            "goal": (
                "Een duurzaam fundament bouwen zonder "
                "vroege wedstrijdvorm na te jagen."
            ),
            "bike_focus": (
                "Overwegend rustige duur, traptechniek "
                "en trainingsregelmaat."
            ),
            "strength_focus": (
                "Meestal twee niet-opeenvolgende "
                "krachtsessies per week indien herstelbaar."
            ),
            "rules": [
                "De meeste fietstijd blijft rustig.",
                "Maximaal één fietskwaliteitssessie per week.",
                "Bouw krachttraining technisch en progressief op.",
                "Vermijd spierfalen en onnodige spierpijn.",
                "Techniek mag laag belastend worden geoefend."
            ]
        }

    if today <= date(2027, 1, 31):
        return {
            "phase": "Basisfase 2",
            "primary_adaptation": (
                "duurzaamheid en musculair uithoudingsvermogen"
            ),
            "goal": (
                "Langere aerobe belasting combineren met "
                "progressieve tempo- of sweet-spottraining."
            ),
            "bike_focus": (
                "Rustige lange duur, tempo, sweet spot "
                "en gecontroleerde krachtuithouding."
            ),
            "strength_focus": (
                "Maximale kracht verder ontwikkelen. "
                "Meestal twee sessies per week indien herstelbaar."
            ),
            "rules": [
                "Plan één progressieve tempo- of sweet-spotsessie.",
                "Plan een tweede fietskwaliteit alleen bij goed herstel.",
                "Behoud minstens één langere rustige duurtraining.",
                "Verhoog krachtbelasting alleen bij goede techniek.",
                "Plaats zware kracht niet vlak voor fietskwaliteit."
            ]
        }

    if today <= date(2027, 3, 15):
        return {
            "phase": "Gerichte opbouw",
            "primary_adaptation": (
                "drempelvermogen en VO2max"
            ),
            "goal": (
                "Aerobe capaciteit, FTP, drempelduur "
                "en VO2max gericht ontwikkelen."
            ),
            "bike_focus": (
                "Drempel, VO2max en voldoende rustige duur."
            ),
            "strength_focus": (
                "Meestal één onderhoudssessie per week. "
                "Een tweede alleen bij lage fietsbelasting."
            ),
            "rules": [
                "Maximaal twee fietskwaliteitssessies per week.",
                "Plan bij voorkeur minimaal 48 uur tussen zware prikkels.",
                "Een zware groepsrit telt als kwaliteitssessie.",
                "Behoud voldoende rustige duur.",
                "Verminder krachtvolume voordat fietskwaliteit wordt geschrapt."
            ]
        }

    if today <= date(2027, 4, 15):
        return {
            "phase": "Koersspecifieke opbouw",
            "primary_adaptation": (
                "herhaalde hoge intensiteit en anaerobe capaciteit"
            ),
            "goal": (
                "Aerobe vorm vertalen naar versnellingen, "
                "herstel tussen inspanningen en sprint na vermoeidheid."
            ),
            "bike_focus": (
                "Herhaalde VO2max-inspanningen, anaerobe capaciteit, "
                "acceleraties en korte kwalitatieve sprints."
            ),
            "strength_focus": (
                "Eén onderhoudssessie per week met beperkt volume."
            ),
            "rules": [
                "Onderhoud drempel met een beperkte dosis.",
                "Voeg herhaalde hoge-intensiteitsinspanningen toe.",
                "Sprint kort, technisch en kwalitatief.",
                "Voorkom drie zware fietsdagen in één week.",
                "Krachttraining mag sprint- of intervalkwaliteit niet verminderen."
            ]
        }

    if today < race_season_start:
        return {
            "phase": "Wedstrijdvoorbereiding",
            "primary_adaptation": (
                "koersscherpte en wedstrijdvaardigheid"
            ),
            "goal": (
                "Fysieke kwaliteiten combineren met positionering, "
                "bochten, tempowissels en sprinttiming."
            ),
            "bike_focus": (
                "Koerssimulaties, snelle groepsritten, "
                "herhaalde acceleraties en sprint na vermoeidheid."
            ),
            "strength_focus": (
                "Korte onderhoudssessie met lage omvang. "
                "Geen onnodige spierpijn."
            ),
            "rules": [
                "Gebruik maximaal één koerssimulatie of snelle groepsrit.",
                "Behoud een tweede gerichte fietskwaliteit alleen indien herstelbaar.",
                "Geen taper zonder werkelijk ingevoerde A-wedstrijd.",
                "Oefen bochten en positionering bewust.",
                "Vermijd opstapelende vermoeidheid."
            ]
        }

    if today <= race_season_end:
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
                "bike_focus": (
                    "Rust of zeer lichte herstelrit."
                ),
                "strength_focus": (
                    "Geen zware krachttraining zolang "
                    "wedstrijdvermoeidheid aanwezig is."
                ),
                "rules": [
                    "Rust of fiets zeer licht.",
                    "Geen gemiste kilometers inhalen.",
                    "Geen zware krachttraining.",
                    "Laat subjectieve feedback en herstel de hervatting bepalen."
                ]
            }

        if (
            next_race
            and next_race["days_until"] == 0
        ):
            return {
                "phase": "Wedstrijddag",
                "primary_adaptation": "wedstrijdprestatie",
                "goal": (
                    "Fris en voorbereid aan de start komen."
                ),
                "bike_focus": (
                    "De wedstrijd is de hoofdtraining."
                ),
                "strength_focus": (
                    "Geen krachttraining."
                ),
                "rules": [
                    "Voer geen extra duurtraining uit.",
                    "Gebruik een functionele warming-up.",
                    "Focus op veilige positionering.",
                    "Bewaar beslissingsvermogen voor de finale.",
                    "Voer geen krachttraining uit."
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
                "bike_focus": (
                    "Lager volume met korte openers."
                ),
                "strength_focus": (
                    "Geen zware krachttraining. Alleen zeer lichte "
                    "activatie wanneer dit vertrouwd is."
                ),
                "rules": [
                    "Verlaag het fietsvolume.",
                    "Behoud enkele korte openers.",
                    "Geen zware drempel- of VO2max-training.",
                    "Geen zware beentraining binnen 48 uur voor de wedstrijd.",
                    "Frisheid is belangrijker dan extra trainingswinst."
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
            "bike_focus": (
                "Wedstrijdspecifieke vorm, rustig volume "
                "en gerichte onderhoudsprikkels."
            ),
            "strength_focus": (
                "Eén korte onderhoudssessie per zeven tot tien dagen "
                "wanneer de wedstrijdkalender dit toestaat."
            ),
            "rules": [
                "Een wedstrijd telt als kwaliteitssessie.",
                "Plan geen twee zware intervals plus een wedstrijd.",
                "Gebruik wedstrijdarme blokken voor gerichte ontwikkeling.",
                "Plan maximaal twee wedstrijdweekends na elkaar.",
                "Plan kracht niet vlak voor een wedstrijd of zware intervaltraining.",
                "Behandel niet iedere wedstrijd als een piekmoment."
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
        "bike_focus": (
            "Rustig en flexibel."
        ),
        "strength_focus": (
            "Tijdelijk verminderen en later opnieuw opbouwen."
        ),
        "rules": [
            "Neem rustige of volledig vrije dagen.",
            "Evalueer het volledige prestatieprofiel.",
            "Start niet onmiddellijk een zwaar nieuw blok.",
            "Bepaal nieuwe doelen na voldoende herstel."
        ]
    }


def determine_recovery_risk(
    summary,
    sleep_info,
    user_feedback
):
    risk_score = 0
    reasons = []

    feedback_text = (
        user_feedback or ""
    ).lower()

    pain_or_illness_words = (
        "pijn",
        "blessure",
        "knie",
        "achilles",
        "scheen",
        "rugpijn",
        "ziek",
        "koorts",
        "verkouden",
        "griep",
        "oververmoeid",
        "uitgeput",
        "zeer moe",
        "zware benen",
        "lege benen",
        "geen energie"
    )

    if any(
        word in feedback_text
        for word in pain_or_illness_words
    ):
        risk_score += 3

        reasons.append(
            "De subjectieve feedback bevat een signaal "
            "rond pijn, ziekte of duidelijke vermoeidheid."
        )

    sleep_score = sleep_info.get(
        "score"
    )

    if sleep_score is None:
        risk_score += 1

        reasons.append(
            "De slaapscore ontbreekt. Herstel wordt "
            "daarom niet automatisch positief beoordeeld."
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

    last_7_days = summary.get(
        "last_7_days",
        {}
    )

    hard_sessions = safe_int(
        last_7_days.get(
            "hard_sessions"
        )
    )

    total_duration = safe_float(
        last_7_days.get(
            "total_duration_h"
        )
    )

    rest_days = last_7_days.get(
        "rest_days_estimate"
    )

    if hard_sessions >= 3:
        risk_score += 2

        reasons.append(
            f"Er waren {hard_sessions} intensieve "
            "sessies in zeven dagen."
        )

    elif hard_sessions == 2:
        risk_score += 1

        reasons.append(
            "Er waren twee intensieve sessies "
            "in de laatste zeven dagen."
        )

    else:
        reasons.append(
            f"Het aantal intensieve sessies in "
            f"zeven dagen is beperkt: {hard_sessions}."
        )

    if (
        rest_days is not None
        and rest_days <= 1
    ):
        risk_score += 1

        reasons.append(
            "Er waren weinig rustdagen "
            "in de laatste zeven dagen."
        )

    elif rest_days is not None:
        reasons.append(
            f"Geschat aantal rustdagen in zeven dagen: "
            f"{rest_days}."
        )

    if total_duration >= 10:
        risk_score += 2

        reasons.append(
            f"Het zeven-daagse trainingsvolume "
            f"is hoog: {total_duration} uur."
        )

    elif total_duration >= 7:
        risk_score += 1

        reasons.append(
            f"Het zeven-daagse trainingsvolume "
            f"is matig tot hoog: {total_duration} uur."
        )

    else:
        reasons.append(
            f"Het zeven-daagse trainingsvolume "
            f"blijft beheersbaar: {total_duration} uur."
        )

    if risk_score >= 5:
        level = "hoog"

        allowed_boundaries = [
            "rust of maximaal een zeer lichte herstelrit",
            "geen intervals",
            "geen sprinttraining",
            "geen zware krachttraining",
            "geen benchmarktest",
            "geen lange duurtraining",
            "geen dubbele trainingsdag"
        ]

    elif risk_score >= 3:
        level = "medium"

        allowed_boundaries = [
            "volume niet verhogen",
            "geen zware krachttraining",
            "hoogstens een korte kwaliteitssessie als de benen goed voelen",
            "geen benchmarktest",
            "geen diepe intervals",
            "geen dubbele trainingsdag"
        ]

    else:
        level = "laag"

        allowed_boundaries = [
            "fasegebonden training toegestaan",
            "maximaal twee kwaliteitssessies per week",
            "bij voorkeur minimaal 48 uur tussen zware prikkels",
            "krachttraining volgens de fase toegestaan",
            "maximaal één hoofdtraining per dag"
        ]

    return {
        "level": level,
        "score": risk_score,
        "reasons": reasons,
        "allowed_training_boundaries": (
            allowed_boundaries
        )
    }


def build_context(
    summary,
    sleep_info,
    weather,
    phase,
    races,
    recent_races,
    recovery,
    athlete_metrics
):
    today = now_be().date()

    return {
        "today": today.isoformat(),
        "weekday": now_be().strftime("%A"),
        "mode": MODUS,

        "athlete_profile": ATHLETE_PROFILE,
        "season_config": SEASON_CONFIG,
        "month_plan_config": MONTH_PLAN_CONFIG,

        "current_training_phase": phase,
        "training_block": determine_block(
            today
        ),

        "race_calendar": (
            race_calendar_summary()
        ),

        "upcoming_races": races,
        "recent_races": recent_races,

        "recovery_risk": recovery,
        "sleep": sleep_info,
        "weather": weather,

        "garmin_summary": summary,
        "athlete_metrics": athlete_metrics,

        "user_feedback": USER_FEEDBACK,
        "extra_context": EXTRA_CONTEXT,

        "hard_constraints": [
            (
                "Het seizoensplan begint altijd "
                "op 1 oktober 2026."
            ),
            (
                "Het seizoensplan loopt tot en met "
                "15 september 2027."
            ),
            (
                "Het prestatiedoel is doorgroeien van "
                "wedstrijden uitrijden naar competitief "
                "meedoen voor de prijzen."
            ),
            (
                "Presenteer meedoen voor de prijzen als "
                "ambitie en niet als gegarandeerde uitkomst."
            ),
            (
                "Optimaliseer allround wielerprestatie. "
                "FTP is belangrijk maar nooit het enige doel."
            ),
            (
                "Gezondheid, continuïteit en herstelbaarheid "
                "gaan voor een losse zware training."
            ),
            (
                "Kies één primaire adaptatie per fase, maand "
                "en week. Onderhoud andere kwaliteiten met "
                "de kleinst effectieve dosis."
            ),
            (
                "Elke kwaliteitstraining moet in een "
                "herkenbare progressie passen."
            ),
            (
                "Verhoog per progressiestap maximaal één "
                "hoofdvariabele: duur, herhalingen, vermogen "
                "of totale omvang."
            ),
            (
                "Maximaal twee fietskwaliteitssessies per week. "
                "Een zware groepsrit en wedstrijd tellen mee."
            ),
            (
                "Behoud voldoende rustige duur en minstens "
                "één rustdag of zeer lichte dag per week."
            ),
            (
                "Gebruik meestal drie progressieve opbouwweken "
                "en één herstelweek, maar hersteldata gaan voor."
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
                "Plan krachttraining doelgericht en fasegebonden."
            ),
            (
                "Plan in de basisperiode meestal twee "
                "niet-opeenvolgende krachtsessies per week "
                "indien herstel dit toelaat."
            ),
            (
                "Plan tijdens de opbouwperiode meestal één "
                "onderhoudende krachtsessie per week."
            ),
            (
                "Plan tijdens de wedstrijdperiode alleen een "
                "korte onderhoudsdosis wanneer die geen "
                "wedstrijd of fietskwaliteit schaadt."
            ),
            (
                "Plan geen zware krachttraining binnen 48 uur "
                "voor een prioritaire wedstrijd."
            ),
            (
                "Plan geen zware beentraining vlak voor "
                "VO2max-, anaerobe of sprinttraining."
            ),
            (
                "Verminder in herstelweken ook het krachtvolume."
            ),
            (
                "Techniek, positionering en bochtenwerk mogen "
                "als laag-belastende vaardigheidsfocus "
                "worden opgenomen."
            ),
            (
                "Maak een maandplan als concreet vier- "
                "of vijfwekenkader."
            ),
            (
                "Een maandplan moet fietsbelasting, "
                "krachttraining, herstel en evaluatie combineren."
            ),
            (
                "Een maandplan mag geen vier identieke "
                "trainingsweken bevatten."
            ),
            (
                "Gebruik de vierde week standaard als herstel- "
                "of consolidatieweek, tenzij wedstrijdkalender "
                "of herstelstatus een andere logica vereist."
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
                "wedstrijd, testhistoriek of prestatieverbetering."
            ),
            (
                "Gemiddeld ritvermogen is geen bewijs van "
                "FTP-stijging of betere koersvorm."
            ),
            (
                "Beoordeel sprint, duurzaamheid en herhaalde "
                "inspanningen alleen wanneer de beschikbare "
                "data dit ondersteunen."
            ),
            (
                "Praktische voeding en hydratatie mogen worden "
                "benoemd, maar zonder medische of absolute claims."
            ),
            (
                "Geef duidelijk aan wat feit uit Garmin is "
                "en wat een coachinschatting is."
            )
        ]
    }


def build_prompt(context):
    output_structures = {
        "dagadvies": """
COACH TAKE

TYPE DAG

HERSTELSTATUS

LAATSTE WORKOUT

VANDAAG
- Exacte training of rust
- Duur
- Intensiteit
- Concrete uitvoering
- Trainingsdoel
- Afbreek- of afschaalcriteria

KRACHTTRAINING
- Alleen opnemen als dit binnen de fase en herstelstatus past.
- Geef aan of kracht vandaag opbouw, onderhoud of niet nodig is.
- Vermijd onnodige spierpijn.

WAAROM NU
Leg de link met:
- huidige trainingsfase
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
- herstel- of afbreekcriterium

KRACHTTRAINING
Geef:
- aantal sessies
- doel per sessie
- plaatsing tegenover fietskwaliteit
- oefenpatronen
- indicatieve sets en herhalingen alleen als coachinschatting
- voorwaarden om af te schalen

BELASTINGSLOGICA
Leg uit waar de zware dagen, rustige dagen en herstelmomenten staan.

PROGRESSIE TEGENOVER DE VORIGE VERGELIJKBARE WEEK

VAARDIGHEID EN KOERSSPECIFIEKE FOCUS

NIET DOEN

FEITEN EN COACHINSCHATTING
""",

        "maandplan": """
COACH TAKE

MAAND EN TRAININGSFASE
- Benoem de gekozen maand.
- Benoem de fase van het seizoen.
- Benoem het relevante trainingsblok.

STARTSITUATIE
- Wat tonen Garmin en subjectieve feedback?
- Wat ontbreekt?
- Maak onderscheid tussen feiten en coachinschatting.

DOEL VAN DE MAAND
Geef één duidelijk hoofddoel voor deze maand.

PRIMAIRE ADAPTATIE
Kies één primaire adaptatie:
- herstel en continuïteit
- aerobe basis
- duurzaamheid
- musculair uithoudingsvermogen
- FTP en drempelduur
- VO2max
- herhaalde hoge intensiteit
- anaerobe capaciteit
- sprint
- koersscherpte
- wedstrijdprestatie

ONDERHOUDSDOELEN
Kies maximaal twee kwaliteiten die met een beperkte dosis worden onderhouden.

WEEK 1
Geef:
- doel van de week
- belangrijkste fietstraining
- duurtraining
- krachttraining
- techniek of vaardigheid
- herstelaccent
- progressiecriterium

WEEK 2
Geef:
- doel van de week
- belangrijkste fietstraining
- duurtraining
- krachttraining
- techniek of vaardigheid
- herstelaccent
- progressie tegenover week 1

WEEK 3
Geef:
- doel van de week
- belangrijkste fietstraining
- duurtraining
- krachttraining
- techniek of vaardigheid
- herstelaccent
- progressie tegenover week 2

WEEK 4 OF HERSTELWEEK
Geef:
- doel van de week
- vermindering van fietsvolume
- aanpassing van intensiteit
- vermindering van krachtvolume
- evaluatie van het trainingsblok
- voorwaarden om het volgende blok te starten

WEEK 5
Voeg dit alleen toe als de kalendermaand daadwerkelijk een vijfde relevante trainingsweek bevat.

KRACHTTRAINING
Geef:
- frequentie
- doel
- plaatsing tegenover fietstrainingen
- oefenpatronen
- indicatieve sets en herhalingen alleen als coachinschatting
- voorwaarden om belasting te verhogen
- voorwaarden om krachttraining af te schalen

BENCHMARK OF EVALUATIE
- Adviseer alleen een test als die binnen de fase past.
- Een FTP-test is niet automatisch verplicht.
- Een vaste klim, tijdrit, intervalbenchmark of herhaalde-sprintbenchmark mag ook.
- Verzin geen testhistoriek.

BIJSTURINGSREGELS
Geef concrete regels voor:
- slechte slaap
- zware benen
- pijn of ziekte
- gemiste training
- onverwachte groepsrit
- uitzonderlijk goede trainingsdag

FEITEN EN COACHINSCHATTING
Maak het onderscheid expliciet.
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
- energie besparen
- beslismomenten
- voorbereiding op de finale

FYSIEKE FOCUS
Welke capaciteit moet gebruikt worden en wat moet niet meer opgebouwd worden?

KRACHTTRAINING
Geef expliciet aan dat zware krachttraining niet meer past vlak voor de wedstrijd.

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

KRACHTONTWIKKELING
Bespreek:
- geregistreerde krachtsessies
- regelmaat
- plaatsing tegenover fietskwaliteit
- mogelijke herstelimpact
- beperkingen in Garmin-data

HERSTELBALANS

AANVULLENDE SPORTEN

VAARDIGHEDEN EN KOERSSPECIFICITEIT
Beoordeel dit alleen als de data of subjectieve feedback het werkelijk tonen.

VOORUITGANG RICHTING MEEDOEN VOOR DE PRIJZEN
- Benoem alleen meetbare of expliciet gerapporteerde vooruitgang.
- Gebruik gemiddeld ritvermogen niet als bewijs.
- Geef aan welke wedstrijdspecifieke informatie ontbreekt.

WAT BEHOUDEN

WAT AANPASSEN

CONCLUSIE VOOR DE KOMENDE TWEE WEKEN
""",

        "seizoen_plan": """
COACH TAKE

STARTPUNT OP 1 OKTOBER 2026
- Benoem het huidige niveau.
- De atleet kan wedstrijden uitrijden.
- Het volgende doel is competitief meedoen voor de prijzen.
- Behandel dit als ambitie, niet als garantie.

SEIZOENSDOEL EN SUCCESCRITERIA
Beschrijf concreet hoe vooruitgang zichtbaar kan worden:
- langer competitief blijven in het peloton
- beter reageren op herhaalde versnellingen
- beter gepositioneerd aan de finale beginnen
- later in de wedstrijd nog vermogen leveren
- finales bereiken
- in geselecteerde wedstrijden voor een uitslag rijden

PRESTATIEPROFIEL
Bespreek:
- aerobe basis
- duurzaamheid
- FTP en drempelduur
- VO2max
- herhaalde hoge intensiteit
- anaerobe capaciteit
- sprint
- kracht
- techniek
- herstel
- databeperkingen

SEIZOENSOPBOUW VAN 1 OKTOBER 2026 TOT EN MET 15 SEPTEMBER 2027

MAANDOVERZICHT

OKTOBER 2026
Geef:
- hoofddoel
- fietsaccent
- krachtaccent
- herstelaccent
- evaluatiemoment

NOVEMBER 2026
Geef:
- hoofddoel
- fietsaccent
- krachtaccent
- herstelaccent
- evaluatiemoment

DECEMBER 2026
Geef:
- hoofddoel
- fietsaccent
- krachtaccent
- herstelaccent
- evaluatiemoment

JANUARI 2027
Geef:
- hoofddoel
- fietsaccent
- krachtaccent
- herstelaccent
- evaluatiemoment

FEBRUARI 2027
Geef:
- hoofddoel
- fietsaccent
- krachtaccent
- herstelaccent
- evaluatiemoment

MAART 2027
Geef:
- hoofddoel
- fietsaccent
- krachtaccent
- herstelaccent
- evaluatiemoment

APRIL 2027
Geef:
- hoofddoel
- fietsaccent
- krachtaccent
- techniekaccent
- herstelaccent
- evaluatiemoment

MEI 2027
Geef:
- hoofddoel
- wedstrijdaccent
- trainingsaccent
- krachtaccent
- herstelaccent

JUNI 2027
Geef:
- hoofddoel
- wedstrijdaccent
- trainingsaccent
- krachtaccent
- herstelaccent

JULI 2027
Geef:
- hoofddoel
- wedstrijdaccent
- trainingsaccent
- krachtaccent
- herstelaccent

AUGUSTUS 2027
Geef:
- hoofddoel
- wedstrijdaccent
- trainingsaccent
- krachtaccent
- herstelaccent

1 TOT EN MET 15 SEPTEMBER 2027
Geef:
- hoofddoel
- wedstrijdaccent
- herstelaccent
- seizoensevaluatie

KRACHTPERIODISERING
Beschrijf:
- gewenning
- algemene kracht
- maximale kracht
- onderhoud
- afbouw rond wedstrijden

WEDSTRIJDPLANNING
Gebruik alleen werkelijk ingevoerde wedstrijden.
Verzin geen wedstrijden of wedstrijddata.

HERSTEL- EN BENCHMARKMOMENTEN
Gebruik vaste en vergelijkbare protocollen.
Plan geen test bij medium of hoog herstelrisico.

BELANGRIJKSTE RANDVOORWAARDEN
Benoem wat het meest bepalend is om van uitrijden naar competitief meedoen door te groeien.
"""
    }

    output_structure = output_structures.get(
        MODUS,
        output_structures["dagadvies"]
    )

    prompt = f"""
Je bent een nuchtere, ervaren wielercoach voor criterium- en wegwielrennen.

Schrijf kort, menselijk, direct en concreet in het Nederlands.

Het seizoensplan begint altijd op 1 oktober 2026 en loopt tot en met 15 september 2027.

De atleet kan momenteel wielerwedstrijden uitrijden. Het doel voor het volgende seizoen is doorgroeien naar competitief meedoen voor de prijzen.

Dit is een ambitieus prestatiedoel en geen gegarandeerde uitkomst.

Het doel is niet een zo hoog mogelijke FTP op papier. De coach moet een compleet wedstrijdprofiel ontwikkelen:

- aerobe basis
- duurzaamheid
- FTP en drempelduur
- VO2max
- herhaalde inspanningen boven drempel
- anaerobe capaciteit
- acceleratie
- sprint
- sprint na vermoeidheid
- kracht
- techniek
- positionering
- koersinzicht
- herstel
- wedstrijdspecifieke frisheid

Coachregels:

- Volg altijd de recovery boundaries en hard constraints uit de context.
- Kies per fase, maand en week één primaire adaptatie.
- Onderhoud andere kwaliteiten met de kleinst effectieve dosis.
- Maak de training geleidelijk wedstrijdspecifieker naarmate mei nadert.
- Gebruik rustige duur, tempo, sweet spot, drempel, VO2max, anaerobe prikkels, sprint, kracht en techniek alleen wanneer ze bij de fase passen.
- Benoem bij iedere training het doel, de plaats in het blok en de beoogde progressie.
- Verhoog per progressiestap maximaal één hoofdvariabele.
- Meer training is niet automatisch betere training.
- Een zware groepsrit of wedstrijd vervangt een kwaliteitssessie.
- Plan niet automatisch twee intervaltrainingen, een zware groepsrit, een wedstrijd en zware kracht in dezelfde week.
- Gebruik herstel als combinatie van slaap, recente belasting en subjectieve feedback.
- Een losse goede of slechte waarde beslist nooit alleen.
- Als interval-, lap- of tijdreeksdata ontbreken, claim dan geen bewezen progressie in FTP, VO2max, sprint of duurzaamheid.
- Gemiddeld ritvermogen van een volledige rit is geen bewijs van wedstrijdvorm.
- Adviseer een benchmark alleen bij laag herstelrisico en na een passend trainingsblok.
- Een FTP-test is niet automatisch de beste benchmark.
- Plan krachttraining zwaarder in de basisperiode en onderhoudend richting wedstrijden.
- Plan zware kracht niet vlak voor een belangrijke fietsprikkel of prioritaire wedstrijd.
- Vermijd trainen tot spierfalen.
- Verminder krachtvolume in herstelweken.
- Verminder tijdens de wedstrijdperiode eerst het aantal sets voordat krachttraining volledig wordt verwijderd.
- Techniek gaat bij krachttraining voor het gebruikte gewicht.
- Voor maandplan: gebruik de maand uit extra_context. Als daar geen maand staat, gebruik de huidige kalendermaand.
- Voor maandplan: voeg alleen week 5 toe als de maand daadwerkelijk een vijfde relevante trainingsweek bevat.
- Voor seizoen_plan: start altijd op 1 oktober 2026, ongeacht de datum waarop deze run wordt uitgevoerd.
- Maak duidelijk onderscheid tussen feiten uit Garmin en coachinschattingen.
- Vermijd clichés, heroische taal, medische claims en verzonnen cijfers.

OUTPUTSTRUCTUUR:

{output_structure}

Context in JSON:

{json.dumps(context, ensure_ascii=False, indent=2)}
"""

    return prompt


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
            "Wielercoach - seizoensplan "
            "oktober 2026 tot september 2027"
        )

    if MODUS == "maandplan":
        requested_month = (
            EXTRA_CONTEXT.strip()
            if EXTRA_CONTEXT.strip()
            else now_be().strftime("%B %Y")
        )

        return (
            f"Wielercoach - maandplan "
            f"{requested_month}"
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

    message = MIMEMultipart()

    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject

    message.attach(
        MIMEText(
            body,
            "plain",
            "utf-8"
        )
    )

    print(
        "[MAIL] Verbinden met smtp.gmail.com:587"
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
            message.as_string()
        )

        if refused:
            raise RuntimeError(
                "Gmail SMTP heeft de ontvanger "
                f"geweigerd: {refused}"
            )

    print(
        "[MAIL] Gmail SMTP heeft de mail aanvaard"
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

    print("[STAP 1] Inloggen bij Garmin")

    garmin = login_garmin_with_retry()

    print("[STAP 2] Activiteiten ophalen")

    if MODUS in {
        "conditie_evolutie",
        "maandplan",
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

    sleep_info = get_sleep_info(
        garmin
    )

    print("[STAP 4] Weer ophalen")

    weather = get_weather_forecast()

    print("[STAP 5] Atleetmetrics ophalen")

    athlete_metrics = detect_athlete_metrics(
        garmin,
        activities
    )

    print("[STAP 6] Activiteiten analyseren")

    summary = summarize_activities(
        activities
    )

    today = now_be().date()

    upcoming_races = next_races(
        today
    )

    recent_races = previous_races(
        today
    )

    phase = determine_training_phase(
        today,
        upcoming_races,
        recent_races
    )

    recovery = determine_recovery_risk(
        summary,
        sleep_info,
        USER_FEEDBACK
    )

    context = build_context(
        summary=summary,
        sleep_info=sleep_info,
        weather=weather,
        phase=phase,
        races=upcoming_races,
        recent_races=recent_races,
        recovery=recovery,
        athlete_metrics=athlete_metrics
    )

    print("[STAP 7] Prompt bouwen")

    prompt = build_prompt(
        context
    )

    print("[STAP 8] Coachadvies genereren")

    ai_text = call_gemini(
        prompt
    )

    recovery_reasons_text = "\n".join(
        f"- {reason}"
        for reason in recovery.get(
            "reasons",
            []
        )
    )

    technical_footer = f"""

--
KORTE DATA-CHECK

Datum: {today.isoformat()}
Modus: {MODUS}

Fase: {phase.get("phase")}
Primaire adaptatie: {phase.get("primary_adaptation")}
Fietsfocus: {phase.get("bike_focus")}
Krachtfocus: {phase.get("strength_focus")}

Trainingsblok: {context.get("training_block")}

Slaapstatus: {sleep_info.get("status")}
Slaapdatum: {sleep_info.get("date")}
Slaapscore: {sleep_info.get("score")}

Recovery risk: {recovery.get("level")} ({recovery.get("score")})

Redenen recovery risk:
{recovery_reasons_text}

Weerbron: {weather.get("source")} - {weather.get("status")}

FTP automatisch: {athlete_metrics.get("ftp")} ({athlete_metrics.get("ftp_source")})
Rusthartslag automatisch: {athlete_metrics.get("resting_hr")} ({athlete_metrics.get("resting_hr_source")})
Max HR automatisch: {athlete_metrics.get("max_hr")} ({athlete_metrics.get("max_hr_source")})

Power-sessies gevonden: {athlete_metrics.get("power_sessions_detected")}
Analyseperiode: {ANALYSEPERIODE_DAGEN} dagen

Activiteiten geladen: {summary.get("data_quality", {}).get("activities_loaded")}
Activiteiten met hartslag: {summary.get("data_quality", {}).get("activities_with_hr")}
Fietsactiviteiten met power: {summary.get("data_quality", {}).get("bike_activities_with_power")}

Wedstrijden ingevoerd: {context.get("race_calendar", {}).get("planned_races")}
A-wedstrijden ingevoerd: {context.get("race_calendar", {}).get("planned_a_races")}

Startniveau: wedstrijden kunnen uitrijden
Seizoensambitie: competitief meedoen voor de prijzen
"""

    final_text = (
        ai_text.strip()
        + technical_footer
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
