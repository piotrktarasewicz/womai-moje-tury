from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import pandas as pd
import requests
from datetime import datetime
import re

app = FastAPI()

# ====== STAŁE ======

today = datetime.now()
CURRENT_YEAR = today.year
CURRENT_MONTH = today.month

# schematy wejść

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

# ====== FUNKCJE ======

def parse_weekendy():
    df = pd.read_csv("grafik.csv")

    weekendy = {}

    for col in df.columns:
        if re.match(r"\d{2}/\d{2}/\d{4}", str(col)):
            date_obj = datetime.strptime(col, "%d/%m/%Y")

            if date_obj.year == CURRENT_YEAR and date_obj.month == CURRENT_MONTH:
                if date_obj.weekday() in [5,6]:  # sobota=5, niedziela=6

                    for value in df[col].dropna():
                        if re.match(r"\d{1,2}:\d{2}-\d{1,2}:\d{2}", str(value)):
                            weekendy[col] = str(value)

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
            "idw": 23,  # nowa ciemność
            "idl": 0,
            "idg": 0
        }
    )

    wynik = {}

    if r.json()["status"] == "complete":
        for item in r.json()["data"]:
            if item["terminGodzina"] in godziny:
                wynik[item["terminGodzina"]] = item["wolne"]

    return wynik


# ====== STRONA ======

@app.get("/", response_class=HTMLResponse)
def moje_tury():

    weekendy = parse_weekendy()

    html = "<h1>Moje Tury – Bieżący miesiąc</h1>"

    for data_str, zakres in weekendy.items():

        wejscia = generuj_wejscia(data_str, zakres)

        date_obj = datetime.strptime(data_str, "%d/%m/%Y")
        data_iso = date_obj.strftime("%Y-%m-%d")

        wolne = pobierz_wolne(data_iso, wejscia)

        html += f"<h2>{data_str} ({zakres})</h2>"

        for godzina in wejscia:
            ile = wolne.get(godzina, "—")
            html += f"<div style='margin-bottom:10px;font-size:22px;'>{godzina}, {ile} wolnych</div>"

    return html
