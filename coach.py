import os
import json
im*ort time
import smtplib
import sys*import traceback
import urllib.req*est
import urllib.parse
from datet*me import datetime, timedelta, dat*
from zoneinfo import ZoneInfo
fro* email.mime.text import MIMEText
f*om email.mime.multipart import MIM*Multipart

from garminconnect impo*t Garmin
from google import genai
*try:
    from groq import Groq
exc*pt Exception:
    Groq = None


# *==================================*========================
# 1. CONF*G
# ==============================*=============================

TIM*ZONE = ZoneInfo("Europe/Brussels")*
GARMIN_EMAIL = os.environ.get("GA*MIN_EMAIL")
GARMIN_WACHTWOORD = os*environ.get("GARMIN_WACHTWOORD")

*EMINI_API_KEY = os.environ.get("GE*INI_API_KEY")
GROQ_API_KEY = os.en*iron.get("GROQ_API_KEY")

GMAIL_AD*ES = os.environ.get("GMAIL_ADRES")*GMAIL_APP_WACHTWOORD = os.environ.*et("GMAIL_APP_WACHTWOORD")
EMAIL_O*TVANGER = os.environ.get("EMAIL_ON*VANGER")

EVENT_NAME = os.environ.*et("GITHUB_EVENT_NAME", "manual")
*EKOZEN_MODUS = os.environ.get("CHO*EN_MODUS") or "dagadvies"

USER_FE*DBACK = os.environ.get("USER_FEEDB*CK") or "Geen actuele subjectieve *eedback opgegeven."
EXTRA_CONTEXT * os.environ.get("EXTRA_CONTEXT") o* ""

MODUS = "dagadvies" if EVENT_*AME == "schedule" else GEKOZEN_MOD*S

# Locatie bij benadering voor D*ndermonde/Berlare-regio.
# Pas aan*indien gewenst.
WEATHER_LAT = 51.0*
WEATHER_LON = 4.10

ATHLETE_PROFI*E = {
    "focus": "optimale vorm *oor wielerwedstrijden",
    "triat*lon_priority": "Triatlon Donkmeer *s puur voor het plezier en mag de *ielervorm niet hypothekeren.",
   *"style": "nuchter, conservatief, c*ncreet, geen heroische taal",
    *max_main_sessions_per_day": 1
}

R*CES = [
    {
        "date": "202*-08-01",
        "name": "Triatlon*Donkmeer",
        "type": "triath*on_fun",
        "priority": "C",
*       "note": "Plezierwedstrijd. *iet pieken. Geen agressieve taper.*Geen onnodige loopbelasting vooraf*"
    },
    {
        "date": "20*6-08-16",
        "name": "Wielerw*dstrijd Haasdonk",
        "type":*"cycling_race",
        "priority"* "A",
        "note": "Eerste hoof*doel. Frisheid, koershardheid en p*nch zijn prioritair."
    },
    {*        "date": "2026-08-22",
    *   "name": "Wielerwedstrijd Sombek*",
        "type": "cycling_race",*        "priority": "A",
        "*ote": "Tweede hoofddoel. Vorm onde*houden, niet opnieuw zware opbouw *tarten."
    },
    {
        "dat*": "2026-08-28",
        "name": "*tomse Pijl Denderhoutem",
        *type": "cycling_fun_race",
       *"priority": "B",
        "note": "*unwedstrijd Cycling Vlaanderen. Ko*rsgericht rijden, maar niet behand*len als hoofdpiek. Ideaal als sche*pe prikkel na Haasdonk en Sombeke.*
    }
]


# =====================*==================================*===
# 2. BASISHELPERS
# ==========*==================================*==============

def require_env(na*e, value):
    if not value:
     *  raise Exception(f"Ontbrekende en*ironment variable of secret: {name*")


def now_be():
    return date*ime.now(TIMEZONE)


def parse_garm*n_datetime(value):
    if not valu*:
        return None

    cleaned*= str(value)[:19].replace("T", " "*

    try:
        return datetime*strptime(cleaned, "%Y-%m-%d %H:%M:*S").replace(tzinfo=TIMEZONE)
    e*cept Exception:
        return Non*


def safe_float(value, default=0*0):
    try:
        if value is N*ne:
            return default
   *    return float(value)
    except*Exception:
        return default
*
def safe_int(value, default=0):
 *  try:
        if value is None:
 *          return default
        r*turn int(value)
    except Excepti*n:
        return default


def fo*mat_duration(seconds):
    seconds*= safe_float(seconds)
    hours = *nt(seconds // 3600)
    minutes = *nt((seconds % 3600) // 60)

    if*hours > 0:
        return f"{hours*u{minutes:02d}"

    return f"{min*tes} min"


def km(meters):
    re*urn round(safe_float(meters) / 100*, 1)


def recursive_find(data, ke*s):
    """
    Robuust zoeken naa* mogelijke slaapvelden in geneste *armin-dicts/lijsten.
    """
    i* isinstance(data, dict):
        f*r key in keys:
            if key *n data and data[key] is not None:
*               return data[key]

 *      for value in data.values():
*           found = recursive_find(*alue, keys)
            if found i* not None:
                return *ound

    elif isinstance(data, li*t):
        for item in data:
    *       found = recursive_find(item* keys)
            if found is not*None:
                return found*
    return None


# =============*==================================*===========
# 3. GARMIN-DATA
# ===*==================================*=====================

def classif*_activity_type(type_key):
    if n*t type_key:
        return "other"*
    t = str(type_key).lower()

  * running = [
        "running",
  *     "street_running",
        "tr*il_running",
        "track_runnin*",
        "treadmill_running",
  *     "indoor_running"
    ]

    c*cling = [
        "cycling",
     *  "road_biking",
        "gravel_c*cling",
        "mountain_biking",*        "indoor_cycling",
        *virtual_ride",
        "bmx",
    *   "cyclocross"
    ]

    swimmin* = [
        "lap_swimming",
     *  "open_water_swimming",
        "*wimming"
    ]

    strength = [
 *      "strength_training",
       *"cardio",
        "hiit",
        *pilates",
        "yoga"
    ]

  * if t in running or "running" in t*
        return "run"

    if t in*cycling or "cycling" in t or "biki*g" in t or "ride" in t:
        re*urn "bike"

    if t in swimming o* "swim" in t:
        return "swim*

    if t in strength:
        re*urn "strength"

    return "other"*

def is_hard_session(activity):
 *  """
    Benadering op basis van *armin Training Effect en gemiddeld* hartslag.
    Dit is geen medisch* logica, enkel een trainingskundig* indicatie.
    """
    aerobic = *afe_float(activity.get("aerobicTra*ningEffect"))
    anaerobic = safe*float(activity.get("anaerobicTrain*ngEffect"))
    avg_hr = safe_floa*(activity.get("averageHR"))
    du*ation = safe_float(activity.get("d*ration"))

    if anaerobic >= 2.0*
        return True

    if aerob*c >= 3.5:
        return True

   *if avg_hr >= 160 and duration >= 1*00:
        return True

    retur* False


def get_sleep_info(garmin*:
    """
    Garmin geeft slaapda*a niet altijd via exact dezelfde s*ructuur terug.

    Deze functie p*obeert:
    - vandaag
    - gister*n
    - meerdere gekende sleepScor*-structuren
    - recursieve fallb*ck
    """
    dates_to_try = [
  *     now_be().date(),
        now_*e().date() - timedelta(days=1)
   *]

    attempts = []

    for d in*dates_to_try:
        d_str = d.st*ftime("%Y-%m-%d")

        try:
  *         sleep_data = garmin.get_s*eep_data(d_str)

            attem*ts.append({
                "date"* d_str,
                "raw_avail*ble": bool(sleep_data)
           *})

            if not sleep_data:*                continue

        *   score = None
            qualit* = None

            daily = sleep*data.get("dailySleepDTO", {}) if i*instance(sleep_data, dict) else {}*
            if isinstance(daily, *ict):
                score = dail*.get("sleepScore")

              * if score is None:
               *    scores = daily.get("sleepScore*", {})
                    if isin*tance(scores, dict):
             *          overall = scores.get("ov*rall", {})
                       *if isinstance(overall, dict):
    *                       score = ove*all.get("value")

                *uality = (
                    dai*y.get("qualityDescription")
      *             or daily.get("sleepSc*reFeedback")
                    o* daily.get("sleepQuality")
       *        )

            if score is*None:
                score = recu*sive_find(
                    sle*p_data,
                    [
    *                   "sleepScore",
 *                      "overallSlee*Score",
                        "s*eepScoreValue"
                   *]
                )

            i* quality is None:
                *uality = recursive_find(
         *          sleep_data,
            *       [
                        "*ualityDescription",
              *         "sleepScoreFeedback",
   *                    "sleepQualityT*pe",
                        "slee*Quality"
                    ]
   *            )

            if scor* is not None:
                scor*_int = safe_int(score, default=-1)*
                if score_int >= 0*
                    return {
    *                   "status": "besc*ikbaar",
                        "*ate": d_str,
                     *  "score": score_int,
            *           "quality": quality or "*een kwaliteitslabel gevonden",
   *                    "note": "Slaap*core gelezen uit Garmin sleep data*"
                    }

        e*cept Exception as e:
            a*tempts.append({
                "d*te": d_str,
                "error*: str(e)
            })

    retur* {
        "status": "niet beschik*aar",
        "date": None,
      * "score": None,
        "quality":*None,
        "note": "Slaapscore *on niet betrouwbaar gelezen worden* Mogelijke oorzaken: Garmin nog ni*t gesynchroniseerd, geen slaapscor* in account, of gewijzigde structu*r in Garmin Connect.",
        "at*empts": attempts
    }


def summa*ize_activities(activities):
    no* = now_be()
    cutoff_7 = now - t*medelta(days=7)
    cutoff_28 = no* - timedelta(days=28)

    structu*ed = []

    for act in activities*
        dt = parse_garmin_datetim*(act.get("startTimeLocal"))
      * discipline = classify_activity_ty*e(act.get("activityType", {}).get(*typeKey"))

        item = {
     *      "name": act.get("activityNam*"),
            "type_key": act.ge*("activityType", {}).get("typeKey"*,
            "discipline": discip*ine,
            "datetime": dt,
 *          "date": dt.strftime("%Y-*m-%d") if dt else None,
          * "distance_m": safe_float(act.get(*distance")),
            "duration*sec": safe_float(act.get("duration*)),
            "average_hr": act.*et("averageHR"),
            "max_*r": act.get("maxHR"),
            *aerobic_te": act.get("aerobicTrain*ngEffect"),
            "anaerobic*te": act.get("anaerobicTrainingEff*ct"),
            "hard": is_hard_*ession(act)
        }

        str*ctured.append(item)

    def summa*ize_since(cutoff, days_window):
  *     filtered = [
            a fo* a in structured
            if a[*datetime"] and a["datetime"] >= cu*off
        ]

        by_disc = {*

        for disc in ["bike", "ru*", "swim", "strength", "other"]:
 *          subset = [
             *  a for a in filtered
            *   if a["discipline"] == disc
    *       ]

            by_disc[disc* = {
                "sessions": l*n(subset),
                "durati*n_sec": round(sum(a["duration_sec"* for a in subset)),
              * "duration_h": round(sum(a["durati*n_sec"] for a in subset) / 3600, 2*,
                "distance_km": r*und(sum(a["distance_m"] for a in s*bset) / 1000, 1)
            }

  *     training_dates = sorted(set(a*"date"] for a in filtered if a["da*e"]))
        hard_sessions = [a f*r a in filtered if a["hard"]]

   *    rest_days_estimate = None
    *   if days_window == 7:
          * rest_days_estimate = max(0, 7 - l*n(training_dates))

        longes*_bike = max(
            [a for a *n filtered if a["discipline"] == "*ike"],
            key=lambda x: x*"duration_sec"],
            defau*t=None
        )

        longest_*un = max(
            [a for a in *iltered if a["discipline"] == "run*],
            key=lambda x: x["du*ation_sec"],
            default=N*ne
        )

        longest_swim*= max(
            [a for a in fil*ered if a["discipline"] == "swim"]*
            key=lambda x: x["dist*nce_m"],
            default=None
*       )

        return {
       *    "total_sessions": len(filtered*,
            "total_duration_h": *ound(sum(a["duration_sec"] for a i* filtered) / 3600, 2),
           *"hard_sessions": len(hard_sessions*,
            "training_days": len*training_dates),
            "rest*days_estimate": rest_days_estimate*
            "by_discipline": by_d*sc,
            "longest_bike": {
*               "date": longest_bik*["date"],
                "duratio*": format_duration(longest_bike["d*ration_sec"]),
                "di*tance_km": km(longest_bike["distan*e_m"])
            } if longest_bi*e else None,
            "longest_*un": {
                "date": lon*est_run["date"],
                "*uration": format_duration(longest_*un["duration_sec"]),
             *  "distance_km": km(longest_run["d*stance_m"])
            } if longe*t_run else None,
            "long*st_swim": {
                "date"* longest_swim["date"],
           *    "duration": format_duration(lo*gest_swim["duration_sec"]),
      *         "distance_km": km(longest*swim["distance_m"])
            } *f longest_swim else None
        }*
    last_10 = []

    for a in st*uctured[:10]:
        last_10.appe*d({
            "date": a["date"],*            "name": a["name"],
   *        "discipline": a["disciplin*"],
            "duration": format*duration(a["duration_sec"]),
     *      "distance_km": km(a["distanc*_m"]),
            "avg_hr": a["av*rage_hr"],
            "aerobic_te*: a["aerobic_te"],
            "an*erobic_te": a["anaerobic_te"],
   *        "hard": a["hard"]
        *)

    latest = structured[0] if s*ructured else None

    quality = *
        "activities_loaded": len(*ctivities),
        "activities_wi*h_datetime": len([a for a in struc*ured if a["datetime"]]),
        "*ctivities_with_hr": len([a for a i* structured if a["average_hr"] is *ot None]),
        "activities_wit*_training_effect": len([
         *  a for a in structured
          * if a["aerobic_te"] is not None or*a["anaerobic_te"] is not None
    *   ])
    }

    return {
        *data_quality": quality,
        "l*st_7_days": summarize_since(cutoff*7, 7),
        "last_28_days": sum*arize_since(cutoff_28, 28),
      * "latest_activity": {
            *date": latest["date"],
           *"name": latest["name"],
          * "discipline": latest["discipline"*,
            "duration": format_d*ration(latest["duration_sec"]),
  *         "distance_km": km(latest[*distance_m"]),
            "avg_hr*: latest["average_hr"],
          * "aerobic_te": latest["aerobic_te"*,
            "anaerobic_te": late*t["anaerobic_te"],
            "ha*d": latest["hard"]
        } if la*est else None,
        "recent_act*vities": last_10
    }


# =======*==================================*=================
# 4. WEER
# ====*==================================*====================

def get_weat*er_forecast():
    """
    Gratis *eerdata via Open-Meteo, zonder API*key.
    """
    try:
        base*url = "https://api.open-meteo.com/*1/forecast"

        params = {
  *         "latitude": WEATHER_LAT,
*           "longitude": WEATHER_LO*,
            "daily": "temperatur*_2m_max,temperature_2m_min,precipi*ation_probability_max,wind_speed_1*m_max",
            "timezone": "E*rope/Brussels",
            "forec*st_days": 5
        }

        url*= base_url + "?" + urllib.parse.ur*encode(params)

        with urlli*.request.urlopen(url, timeout=15) *s response:
            data = jso*.loads(response.read().decode("utf*8"))

        daily = data.get("da*ly", {})
        days = daily.get(*time", [])
        tmax = daily.ge*("temperature_2m_max", [])
       *tmin = daily.get("temperature_2m_m*n", [])
        rain = daily.get("*recipitation_probability_max", [])*        wind = daily.get("wind_spe*d_10m_max", [])

        forecast * []

        for i, d in enumerate*days):
            forecast.append*{
                "date": d,
     *          "temp_min_c": tmin[i] if*i < len(tmin) else None,
         *      "temp_max_c": tmax[i] if i <*len(tmax) else None,
             *  "rain_probability_pct": rain[i] *f i < len(rain) else None,
       *        "max_wind_kmh": wind[i] if*i < len(wind) else None
          * })

        return {
            *source": "Open-Meteo",
           *"status": "beschikbaar",
         *  "forecast": forecast
        }

*   except Exception as e:
        *eturn {
            "source": "Ope*-Meteo",
            "status": "ni*t beschikbaar",
            "error*: str(e),
            "forecast": *]
        }


# ==================*==================================*======
# 5. WEDSTRIJD- EN FASELOGI*A
# ==============================*=============================

def*next_races(today):
    result = []*
    for race in RACES:
        ra*e_date = datetime.strptime(race["d*te"], "%Y-%m-%d").date()
        d*ys_until = (race_date - today).day*

        if days_until >= 0:
    *       enriched = dict(race)
     *      enriched["days_until"] = day*_until
            result.append(e*riched)

    return result


def d*termine_training_phase(today):
   *"""
    Planning rond de opgegeven*wedstrijden.

    Prioriteiten:
  * - Haasdonk: A
    - Sombeke: A
  * - Atomse Pijl Denderhoutem: B, fu*wedstrijd
    - Triatlon Donkmeer:*C, plezier
    """
    d = today

*   if d <= date(2026, 7, 27):
    *   return {
            "phase": "*ike build met gecontroleerd triatl*nonderhoud",
            "goal": "*oersspecifieke fietsconditie opbou*en zonder extra loopvermoeidheid."*
            "rules": [
          *     "Fietsen is hoofdprioriteit."*
                "Zwemmen mag tech*iek of herstel zijn.",
           *    "Lopen blijft kort en comforta*el.",
                "Geen zware *oopintervallen.",
                *Maximaal twee intensieve fietsprik*els per week.",
                "G*en onnodige bricktrainingen."
    *       ]
        }

    if date(20*6, 7, 28) <= d <= date(2026, 7, 31*:
        return {
            "ph*se": "Lichte taper richting Triatl*n Donkmeer als plezierwedstrijd",
*           "goal": "Fris genoeg bl*jven voor Donkmeer, zonder echte t*iatlonpiek te creëren.",
         *  "rules": [
                "Geen*zware looptrainingen.",
          *     "Korte fietsopeners zijn toeg*staan.",
                "Zwemmen *lleen technisch en ontspannen.",
 *              "Geen vermoeidheid c*eëren voor het wielerblok in augus*us.",
                "Triatlonvoo*bereiding mag de fietsfocus niet v*rstoren."
            ]
        }
*    if d == date(2026, 8, 1):
    *   return {
            "phase": "*riatlon Donkmeer racedag",
       *    "goal": "Genieten, gecontrolee*d afwerken en geen diepe put grave*.",
            "rules": [
       *        "Triatlon is geen hoofddoe*.",
                "Niet forceren*in het lopen.",
                "F*etsen stevig maar gecontroleerd.",*                "Na afloop focus o* herstel.",
                "Geen *xtra training naast de wedstrijd."*            ]
        }

    if da*e(2026, 8, 2) <= d <= date(2026, 8* 5):
        return {
            *phase": "Herstel na Triatlon Donkm*er",
            "goal": "Vermoeid*eid laten zakken en fietsbenen opn*euw activeren.",
            "rule*": [
                "Geen intensi*ve looptraining.",
               *"Geen lange duurtraining.",
      *         "Lichte fietsritten en he*stel zijn prioritair.",
          *     "Pas intensiteit toevoegen al* benen fris aanvoelen.",
         *      "Focus op herstel richting H*asdonk."
            ]
        }

*   if date(2026, 8, 6) <= d <= dat*(2026, 8, 12):
        return {
  *         "phase": "Laatste koerssp*cifieke build richting Haasdonk",
*           "goal": "Punch, VO2 en *erhaalde versnellingen aanscherpen*",
            "rules": [
        *       "Een of twee korte intensie*e fietsprikkels in deze periode.",*                "Geen loopbelastin* die fietsfrisheid aantast.",
    *           "Rustdagen respecteren.*,
                "Geen onnodig vo*ume.",
                "Koersspeci*iek werken: korte versnellingen, p*sitionering, tempowissels."
      *     ]
        }

    if date(2026* 8, 13) <= d <= date(2026, 8, 16):*        return {
            "phas*": "Taper richting Wielerwedstrijd*Haasdonk",
            "goal": "Fr*s, scherp en explosief aan de star* komen.",
            "rules": [
 *              "Volume sterk beperk*n.",
                "Korte opener*, geen zware blokken.",
          *     "Geen looptraining meer tenzi* zeer kort en los.",
             *  "Slaap en herstel primeren.",
  *             "Geen training die sp*erpijn of diepe vermoeidheid kan v*roorzaken."
            ]
        *

    if date(2026, 8, 17) <= d <=*date(2026, 8, 18):
        return *
            "phase": "Herstel na *aasdonk",
            "goal": "Spi*rvermoeidheid en koersstress laten*zakken.",
            "rules": [
 *              "Alleen herstelrit o* rust.",
                "Geen int*nsiteit.",
                "Geen l*opbelasting.",
                "Ev*lueren hoe diep de wedstrijd zat."*            ]
        }

    if da*e(2026, 8, 19) <= d <= date(2026, *, 21):
        return {
          * "phase": "Aanscherpen richting So*beke",
            "goal": "Vorm b*houden met minimale vermoeidheid."*
            "rules": [
          *     "Korte intensiteit mag, maar *een lange blokken.",
             *  "Volume laag houden.",
         *      "Geen zware krachttraining."*
                "Frisheid is bela*grijker dan extra trainingswinst."*
                "Geen looptrainin* die de fietsbenen belast."
      *     ]
        }

    if d == date*2026, 8, 22):
        return {
   *        "phase": "Wielerwedstrijd *ombeke racedag",
            "goal*: "Koersprestatie maximaliseren.",*            "rules": [
           *    "Geen extra training.",
      *         "Korte activatie indien n*dig.",
                "Voeding en*warming-up concreet houden.",
    *           "Focus op positionering*en herhaalde versnellingen."
     *      ]
        }

    if date(202*, 8, 23) <= d <= date(2026, 8, 24)*
        return {
            "pha*e": "Herstel na Sombeke",
        *   "goal": "Herstellen zonder vorm*erlies.",
            "rules": [
 *              "Rust of zeer lichte*fietsrit.",
                "Geen *ntensiteit.",
                "Gee* loopbelasting.",
                *Check vermoeidheid en slaap."
    *       ]
        }

    if date(20*6, 8, 25) <= d <= date(2026, 8, 27*:
        return {
            "ph*se": "Aanscherpen richting Atomse *ijl Denderhoutem",
            "go*l": "Scherpte behouden voor de fun*edstrijd, zonder nog vermoeidheid *p te bouwen.",
            "rules"* [
                "Korte koerspri*kels toegestaan.",
               *"Geen lange duurtraining meer.",
 *              "Geen diepe interval*.",
                "Geen loopbela*ting.",
                "Frisheid *elangrijker dan extra trainingswin*t.",
                "Denderhoutem*is een funwedstrijd: scherp starte*, maar niet forceren als het licha*m vermoeid is na Haasdonk en Sombe*e."
            ]
        }

    i* d == date(2026, 8, 28):
        r*turn {
            "phase": "Atoms* Pijl Denderhoutem racedag",
     *      "goal": "Koersgericht rijden*met focus op fun, positionering en*korte versnellingen.",
           *"rules": [
                "Geen e*tra training naast de wedstrijd.",*                "Korte warming-up *et enkele korte versnellingen.",
 *              "Niet starten alsof *it een A-piek is.",
              * "Gebruik de wedstrijd als scherpe*koersprikkel.",
                "F*cus op veilig rijden, positionerin* en doseren op eventuele selectiev* stukken."
            ]
        }*
    return {
        "phase": "Po*t-race overgang",
        "goal": *Herstel, evaluatie en nieuwe doele* bepalen.",
        "rules": [
   *        "Geen automatische zware o*bouw.",
            "Eerst herstel*tatus evalueren.",
            "Ni*uwe doelstelling bepalen voor volg*nde blok."
        ]
    }


# ===*==================================*=====================
# 6. HERSTEL* EN RISICOLOGICA
# ===============*==================================*=========

def determine_recovery_*isk(summary, sleep_info, user_feed*ack):
    reasons = []
    risk_sc*re = 0

    lower_feedback = (user*feedback or "").lower()

    pain_*ords = [
        "pijn",
        "*lessure",
        "knie",
        *achilles",
        "scheen",
     *  "rug",
        "ziek",
        "*oorts",
        "verkouden",
     *  "oververmoeid",
        "uitgepu*",
        "zeer moe",
        "sl*cht geslapen",
        "zware bene*",
        "lege benen",
        "*een energie"
    ]

    if any(wor* in lower_feedback for word in pai*_words):
        risk_score += 3
 *      reasons.append("Subjectieve *eedback bevat pijn/vermoeidheid/zi*kte-indicatie.")

    if sleep_inf*.get("score") is not None:
       *score = safe_int(sleep_info.get("s*ore"))

        if score < 60:
   *        risk_score += 3
          * reasons.append(f"Slaapscore is ze*r laag: {score}/100.")
        eli* score < 70:
            risk_scor* += 2
            reasons.append(f*Slaapscore is laag: {score}/100.")*        elif score < 78:
         *  risk_score += 1
            reas*ns.append(f"Slaapscore is matig: {*core}/100.")
    else:
        ris*_score += 1
        reasons.append*"Slaapscore ontbreekt; geen positi*ve herstelconclusie trekken.")

  * last_7 = summary.get("last_7_days*, {})
    hard_sessions = safe_int*last_7.get("hard_sessions"))
    t*tal_h = safe_float(last_7.get("tot*l_duration_h"))
    rest_days = la*t_7.get("rest_days_estimate")

   *if hard_sessions >= 3:
        ris*_score += 2
        reasons.append*f"Veel intensieve sessies in de la*tste 7 dagen: {hard_sessions}.")
 *  elif hard_sessions == 2:
       *risk_score += 1
        reasons.ap*end("Twee intensieve sessies in de*laatste 7 dagen.")

    if rest_da*s is not None and rest_days <= 1:
*       risk_score += 1
        rea*ons.append("Weinig rustdagen in de*laatste 7 dagen.")

    if total_h*>= 10:
        risk_score += 2
   *    reasons.append(f"Hoog totaalvo*ume laatste 7 dagen: {total_h} uur*")
    elif total_h >= 7:
        *isk_score += 1
        reasons.app*nd(f"Matig tot hoog totaalvolume l*atste 7 dagen: {total_h} uur.")

 *  if risk_score >= 5:
        leve* = "hoog"
        allowed = [
    *       "rust",
            "mobili*eit",
            "zeer lichte her*telrit 30-45 min",
            "ea*y swim techniek",
            "gee* intervals",
            "geen lan*e duur",
            "geen brick",*            "geen zware looptraini*g",
            "geen dubbele trai*ingsdag"
        ]
    elif risk_s*ore >= 3:
        level = "medium"*        allowed = [
            "l*chte tot matige training",
       *    "maximaal korte fietsprikkel a*s de benen goed voelen",
         *  "volume niet verhogen",
        *   "geen zware loopbelasting",
   *        "geen dubbele trainingsdag*,
            "geen diepe interval*"
        ]
    else:
        leve* = "laag"
        allowed = [
    *       "normale geplande fietstrai*ing toegestaan",
            "maxi*aal een hoofdtraining per dag",
  *         "intensiteit alleen als d*t past binnen de fase",
          * "looptraining ondergeschikt aan f*etsfocus",
            "geen onnodige extra sessies"
        ]

    return {
        "level": level,
        "score": risk_score,
        "reasons": reasons,
        "allowed_training_boundaries": allowed
    }


# ============================================================
# 7. PROMPT EN AI-CALLS
# ============================================================

def build_coach_context(summary, sleep_info, weather, phase, races, recovery):
    today = now_be().date()

    return {
        "today": today.strftime("%Y-%m-%d"),
        "weekday": now_be().strftime("%A"),
        "mode": MODUS,
        "athlete_profile": ATHLETE_PROFILE,
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
            "Geen heroische taal, geen overdreven motivatie."
        ]
    }


def build_prompt(context):
    if MODUS == "week_schema":
        output_instruction = """
Maak een compact weekschema vanaf vandaag tot en met zondag.
Focus op fietsvorm, frisheid en koersspecifieke prikkels.
Geef per dag maximaal een hoofdtraining.
De week mag geen triatlon-focus krijgen.
"""
    elif MODUS == "workout_feedback":
        output_instruction = """
Analyseer vooral de meest recente activiteit.
Leg uit wat deze training betekent voor de fietsvoorbereiding en wat morgen verstandig is.
"""
    elif MODUS == "race_readiness":
        output_instruction = """
Geef een race-readiness check voor de eerstvolgende wielerwedstrijd.
Focus op frisheid, scherpte, risico's en de laatste 72 uur.
"""
    elif MODUS == "herstel_check":
        output_instruction = """
Geef een hersteladvies.
Focus op slaap, vermoeidheid, pijnsignalen en wat absoluut niet te doen.
"""
    else:
        output_instruction = """
Geef een dagadvies voor vandaag en een target voor morgen.
Focus op fietsontwikkeling en frisheid richting de wielerwedstrijden.
"""

    prompt = f"""
Je bent een nuchtere, conservatieve wielercoach met basiskennis triatlon.
Je atleet wil optimaal presteren in de wielerwedstrijden in augustus 2026.
De triatlon op 1 augustus is puur voor het plezier en mag de wielervorm niet schaden.

Belangrijk:
- Wees concreet.
- Geen heroische taal.
- Geen overdreven motivatie.
- Geen medisch advies.
- Bij twijfel kies je herstel of lagere intensiteit.
- Adviseer nooit zwaarder dan de recovery boundaries toestaan.
- Maximaal een hoofdtraining per dag.
- Lopen is ondergeschikt aan fietsfrisheid.
- Zwemmen mag vooral herstel of techniek zijn.
- Respecteer expliciet de prioriteit van de wedstrijden:
  1. Haasdonk: A-wedstrijd
  2. Sombeke: A-wedstrijd
  3. Atomse Pijl Denderhoutem: B/funwedstrijd
  4. Triatlon Donkmeer: C/plezierwedstrijd

OUTPUTSTRUCTUUR IN HOOFDLETTERS:

STATUS
- 3 tot 6 bullets over slaap, belasting, weer, fase en eerstvolgende wedstrijd.

ADVIES VANDAAG
- Exacte training of rust.
- Duur.
- Intensiteit.
- Waarop letten.
- Wanneer afbreken.

WAAROM DIT ADVIES
- Korte onderbouwing op basis van data.

MORGEN
- Target workout of hersteladvies.

NIET DOEN
- 2 tot 4 duidelijke zaken die vandaag vermeden moeten worden.

WEDSTRIJDFOCUS
- Een korte link met de komende wielerwedstrijden.

Specifieke opdracht voor deze run:
{output_instruction}

Context in JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}
"""

    return prompt


def call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY ontbreekt.")

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

            except Exception as e:
                last_error = e
                error_text = str(e).lower()

                if (
                    "503" in error_text
                    or "unavailable" in error_text
                    or "rate" in error_text
                    or "429" in error_text
                    or "resource_exhausted" in error_text
                ):
                    time.sleep(10)
                else:
                    raise

    raise Exception(f"Gemini gaf geen bruikbare output. Laatste fout: {last_error}")


def call_groq(prompt):
    if not GROQ_API_KEY:
        raise Exception("GROQ_API_KEY ontbreekt.")

    if Groq is None:
        raise Exception("Groq package is niet beschikbaar.")

    client = Groq(api_key=GROQ_API_KEY)

    models_to_try = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant"
    ]

    last_error = None

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                print(f"Groq call: {model_name}, poging {attempt + 1}/3")

                completion = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "Je bent een nuchtere wielercoach. Antwoord in het Nederlands, concreet, conservatief en kort."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.2,
                    max_tokens=1800
                )

                text = completion.choices[0].message.content

                if text and text.strip():
                    return text.strip()

            except Exception as e:
                last_error = e
                time.sleep(10)

    raise Exception(f"Groq gaf geen bruikbare output. Laatste fout: {last_error}")


def generate_ai_text(prompt):
    """
    Gratis-first:
    1. Gemini
    2. Groq fallback als GROQ_API_KEY bestaat
    """
    errors = []

    try:
        return call_gemini(prompt)
    except Exception as e:
        errors.append(f"Gemini fout: {str(e)}")
        print(errors[-1])

    if GROQ_API_KEY:
        try:
            return call_groq(prompt)
        except Exception as e:
            errors.append(f"Groq fout: {str(e)}")
            print(errors[-1])

    raise Exception("Geen AI-output beschikbaar. " + " | ".join(errors))


# ============================================================
# 8. MAIL
# ============================================================

def subject_for_mode(context):
    races = context.get("upcoming_races", [])
    next_race = races[0] if races else None

    if next_race:
        race_part = f"{next_race['name']} over {next_race['days_until']} dagen"
    else:
        race_part = "geen komende wedstrijd gevonden"

    if MODUS == "week_schema":
        return f"Wielercoach - weekschema richting {race_part}"

    if MODUS == "workout_feedback":
        return f"Wielercoach - workout feedback richting {race_part}"

    if MODUS == "race_readiness":
        return f"Wielercoach - race readiness richting {race_part}"

    if MODUS == "herstel_check":
        return f"Wielercoach - herstelcheck richting {race_part}"

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


# ============================================================
# 9. MAIN
# ============================================================

def main():
    require_env("GARMIN_EMAIL", GARMIN_EMAIL)
    require_env("GARMIN_WACHTWOORD", GARMIN_WACHTWOORD)
    require_env("GMAIL_ADRES", GMAIL_ADRES)
    require_env("GMAIL_APP_WACHTWOORD", GMAIL_APP_WACHTWOORD)
    require_env("EMAIL_ONTVANGER", EMAIL_ONTVANGER)

    if not GEMINI_API_KEY and not GROQ_API_KEY:
        raise Exception("Er is geen AI API key ingesteld. Minstens GEMINI_API_KEY of GROQ_API_KEY is nodig.")

    print("[STAP 1] Inloggen bij Garmin")

    token_dir = os.path.expanduser("~/.garminconnect")
    os.makedirs(token_dir, exist_ok=True)

    garmin = Garmin(GARMIN_EMAIL, GARMIN_WACHTWOORD)
    garmin.login(token_dir)

    print("[STAP 2] Garmin activiteiten ophalen")

    activities = garmin.get_activities(0, 60)

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

    ai_text = generate_ai_text(prompt)

    technical_footer = f"""

--
DATAKWALITEIT
Slaapstatus: {sleep_info.get("status")}
Slaapdatum: {sleep_info.get("date")}
Slaapscore: {sleep_info.get("score")}
Slaapnota: {sleep_info.get("note")}
Weerbron: {weather.get("source")} - {weather.get("status")}
Recovery risk: {recovery.get("level")} ({recovery.get("score")})
Modus: {MODUS}
Garmin activiteiten geladen: {summary.get("data_quality", {}).get("activities_loaded")}
Activiteiten met hartslag: {summary.get("data_quality", {}).get("activities_with_hr")}
Activiteiten met Training Effect: {summary.get("data_quality", {}).get("activities_with_training_effect")}
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
        print("\n" + "=" * 60)
        print("CRITICAL ERROR")
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60 + "\n")
        sys.exit(1)
