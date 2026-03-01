from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
from datetime import datetime
import re

app = FastAPI()

today = datetime.now()
CURRENT_YEAR = today.year
CURRENT_MONTH = today.month

# ===== SCHEMATY =====

SOBOTA_SCHEMATY = {
    "10:30-17:00": ["11:00","12:00","13:00","15:00","16:00"],
    "12:40-19:40": ["12:40","13:40","14:40","16:40","17:40","18:40"],
    "14:00-20:00": ["14:00","15:40","17:00","18:00","19:00"]
}

NIEDZIELA_SCHEMATY = {
    "09:30-16:00": ["10:00","11:00","12:00","14:00","15:00"],
    "11:40-18:40": ["11:40","12:40","13:40","15:40","16:40","17:40"],
    "13:00-19:00": ["13:00","14:20","16:00","17:00","18:00"]
}

# ===== PARSER =====

def parse_weekendy():
    weekendy = {}

    with open("grafik.csv", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(",")

            if len(parts) < 4:
                continue

            if re.match(r"\d{2}/\d{2}/\d{4}", parts[0]):

                data_str = parts[0]
                dzien = parts[1].lower()

                if "sobota" in dzien or "niedziela" in dzien:

                    start = parts[2]
                    koniec = parts[3]

                    if start not in ["off","L4"] and ":" in start:

                        date_obj = datetime.strptime(data_str, "%d/%m/%Y")

                        if date_obj.year == CURRENT_YEAR and date_obj.month == CURRENT_MONTH:

                            zakres = f"{start}-{koniec}"
                            weekendy[data_str] = zakres

    return weekendy


def generuj_wejscia(data_str, zakres):
    date_obj = datetime.strptime(data_str, "%d/%m/%Y")

    if date_obj.weekday() == 5:
        return SOBOTA_SCHEMATY.get(zakres, [])
    else:
        return NIEDZIELA_SCHEMATY.get(zakres, [])


def pobierz_wolne(data_iso, godziny):
    r = requests.get(
        "https://www.rezerwacja.womai.pl/index/ajax.html",
        params={
            "ajax": "pobierzTerminy",
            "selectedDate": data_iso,
            "idw": 23,
            "idl": 0,
            "idg": 0
        }
    )

    wynik = {}

    json_data = r.json()

    if json_data["status"] == "complete":
        for item in json_data["data"]:
            if item["terminGodzina"] in godziny:
                wynik[item["terminGodzina"]] = item["wolne"]

    return wynik


# ===== STRONA =====

@app.get("/", response_class=HTMLResponse)
def moje_tury():

    weekendy = parse_weekendy()

    html = "<h1>Moje Tury – Bieżący miesiąc</h1>"

    if not weekendy:
        html += "<p>Brak weekendowych zmian w tym miesiącu.</p>"
        return html

    for data_str, zakres in sorted(weekendy.items()):

        wejscia = generuj_wejscia(data_str, zakres)

        date_obj = datetime.strptime(data_str, "%d/%m/%Y")
        data_iso = date_obj.strftime("%Y-%m-%d")

        wolne = pobierz_wolne(data_iso, wejscia)

        html += f"<h2>{data_str} ({zakres})</h2>"

        for godzina in wejscia:
            ile = wolne.get(godzina, "—")
            html += f"<div style='margin-bottom:10px;font-size:22px;'>{godzina}, {ile} wolnych</div>"

    return html
