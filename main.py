from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import requests
from datetime import datetime
import re

app = FastAPI()

today = datetime.now()
CURRENT_YEAR = today.year
CURRENT_MONTH = today.month
TODAY_DATE = today.date()

# ===== SCHEMATY WEJŚĆ =====

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

# ===== IDW LOGIKA =====

def pobierz_idw(date_obj):
    granica = datetime(2026, 3, 1)
    if date_obj >= granica:
        return [23, 24]
    else:
        return [1, 17]

# ===== PARSER GRAFIKU =====

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

                            if date_obj.date() >= TODAY_DATE:

                                start = start.zfill(5)
                                koniec = koniec.zfill(5)

                                zakres = f"{start}-{koniec}"
                                data_iso = date_obj.strftime("%Y-%m-%d")

                                weekendy[data_iso] = {
                                    "data_pl": data_str,
                                    "zakres": zakres
                                }

    return weekendy

def generuj_wejscia(data_iso, zakres):
    date_obj = datetime.strptime(data_iso, "%Y-%m-%d")

    if date_obj.weekday() == 5:
        return SOBOTA_SCHEMATY.get(zakres, [])
    else:
        return NIEDZIELA_SCHEMATY.get(zakres, [])

def pobierz_wolne(data_iso, godziny):

    idw_lista = pobierz_idw(datetime.strptime(data_iso, "%Y-%m-%d"))
    wynik = {}

    for idw in idw_lista:
        r = requests.get(
            "https://www.rezerwacja.womai.pl/index/ajax.html",
            params={
                "ajax": "pobierzTerminy",
                "selectedDate": data_iso,
                "idw": idw,
                "idl": 0,
                "idg": 0
            }
        )

        json_data = r.json()

        if json_data["status"] == "complete":
            for item in json_data["data"]:
                if item["terminGodzina"] in godziny:
                    wynik[item["terminGodzina"]] = item["wolne"]

    return wynik

# ===== STRONA WYBORU DNIA =====

@app.get("/", response_class=HTMLResponse)
def lista_dni():

    weekendy = parse_weekendy()

    html = "<h1>Wybierz dzień</h1>"

    if not weekendy:
        html += "<p>Brak nadchodzących weekendowych zmian.</p>"
        return html

    for data_iso, dane in sorted(weekendy.items()):

        html += f"""
        <form method="get" action="/dzien" style="margin-bottom:20px;">
            <input type="hidden" name="data" value="{data_iso}">
            <button style="font-size:24px;padding:12px 20px;width:100%;">
                {dane["data_pl"]} ({dane["zakres"]})
            </button>
        </form>
        """

    return html

# ===== STRONA DNIA =====

@app.get("/dzien", response_class=HTMLResponse)
def pokaz_dzien(request: Request):

    data_iso = request.query_params.get("data")
    weekendy = parse_weekendy()

    if data_iso not in weekendy:
        return "<h1>Nieprawidłowa data</h1>"

    dane = weekendy[data_iso]
    wejscia = generuj_wejscia(data_iso, dane["zakres"])
    wolne = pobierz_wolne(data_iso, wejscia)

    html = f"<h1>{dane['data_pl']} ({dane['zakres']})</h1>"

    znalezione = False

    for godzina in wejscia:
        if godzina in wolne:
            znalezione = True
            html += f"<div style='margin-bottom:12px;font-size:24px;'>{godzina}, {wolne[godzina]} wolnych</div>"

    if not znalezione:
        html += "<p>Brak aktywnych wejść w systemie sprzedaży.</p>"

    html += """
    <div style="margin-top:30px;">
        <a href="/" style="font-size:22px;">Powrót do wyboru dnia</a>
    </div>
    """

    return html
