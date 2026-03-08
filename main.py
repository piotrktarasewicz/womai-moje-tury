from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import csv
import html
import os
from datetime import date, datetime
import requests

app = FastAPI()

GRAFIK_FILE = "grafik.csv"
API_URL = "https://www.rezerwacja.womai.pl/index/ajax.html"
REQUEST_TIMEOUT = 12
GRANICA_IDW = date(2026, 3, 1)

MIESIACE = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia"
]

SCHEMATY_SOBOTA = {
    ("10:30", "17:00"): ["11:00", "12:00", "13:00", "15:00", "16:00"],
    ("12:40", "19:40"): ["12:40", "13:40", "14:40", "16:40", "17:40", "18:40"],
    ("14:00", "20:00"): ["14:00", "15:40", "17:00", "18:00", "19:00"],
}

SCHEMATY_NIEDZIELA = {
    ("09:30", "16:00"): ["10:00", "11:00", "12:00", "14:00", "15:00"],
    ("11:40", "18:40"): ["11:40", "12:40", "13:40", "15:40", "16:40", "17:40"],
    ("13:00", "19:00"): ["13:00", "14:20", "16:00", "17:00", "18:00"],
}

DNI_WEEKEND = {"Sat", "Sun"}
DNI_WEEKEND_PL = {"sobota", "niedziela"}


def dzisiaj():
    return date.today()


def render_page(title: str, body: str) -> HTMLResponse:
    safe_title = html.escape(title)
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>{safe_title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{
    font-family: Arial, sans-serif;
    font-size: 22px;
    line-height: 1.5;
    padding: 20px;
}}
select, button {{
    font-size: 22px;
    padding: 8px;
    margin-top: 10px;
}}
a.button-link {{
    display: inline-block;
    font-size: 22px;
    padding: 8px 12px;
    margin-top: 20px;
    border: 1px solid #444;
    text-decoration: none;
    color: inherit;
}}
</style>
</head>
<body>
{body}
</body>
</html>"""
    )


def normalizuj_godzine(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""

    if value.lower() in {"off", "l4"}:
        return value.lower()

    parts = value.split(":")
    if len(parts) != 2:
        return value

    try:
        hh = int(parts[0])
        mm = int(parts[1])
        return f"{hh:02d}:{mm:02d}"
    except ValueError:
        return value


def parse_date_cell(value: str):
    value = (value or "").strip()
    if not value:
        return None

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def wczytaj_csv():
    if not os.path.exists(GRAFIK_FILE):
        raise FileNotFoundError(f"Brak pliku {GRAFIK_FILE}")

    rows = []
    with open(GRAFIK_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)

    return rows


def znajdz_naglowek_i_wiersz_grafiku(rows):
    header_row = None
    grafik_row = None

    for row in rows:
        if len(row) >= 2 and row[0].strip() == "Krzysztof" and row[1].strip() == "Tarasewicz":
            grafik_row = row
            break

    if grafik_row is None:
        raise ValueError("Nie znaleziono wiersza z grafikiem Krzysztofa Tarasewicza.")

    for row in rows:
        found_date = False
        found_weekend_marker = False

        for cell in row:
            cell_stripped = (cell or "").strip()
            if parse_date_cell(cell_stripped):
                found_date = True
            if cell_stripped in DNI_WEEKEND:
                found_weekend_marker = True

        if found_date and found_weekend_marker:
            header_row = row
            break

    if header_row is None:
        raise ValueError("Nie znaleziono wiersza nagłówkowego z datami i dniami tygodnia.")

    return header_row, grafik_row


def pobierz_weekendowe_zmiany():
    rows = wczytaj_csv()
    header_row, grafik_row = znajdz_naglowek_i_wiersz_grafiku(rows)

    today = dzisiaj()
    results = []

    max_len = max(len(header_row), len(grafik_row))

    for i in range(max_len):
        cell = header_row[i].strip() if i < len(header_row) and header_row[i] else ""
        dt = parse_date_cell(cell)

        if not dt:
            continue

        day_name = header_row[i + 2].strip() if i + 2 < len(header_row) and header_row[i + 2] else ""
        if day_name not in DNI_WEEKEND:
            continue

        if dt < today:
            continue

        start_raw = grafik_row[i + 2].strip() if i + 2 < len(grafik_row) and grafik_row[i + 2] else ""
        end_raw = grafik_row[i + 3].strip() if i + 3 < len(grafik_row) and grafik_row[i + 3] else ""

        start = normalizuj_godzine(start_raw)
        end = normalizuj_godzine(end_raw)

        if start in {"off", "l4", ""} or end in {"off", "l4", ""}:
            continue

        if day_name == "Sat":
            wejscia = SCHEMATY_SOBOTA.get((start, end))
            dzien_tygodnia = "sobota"
        else:
            wejscia = SCHEMATY_NIEDZIELA.get((start, end))
            dzien_tygodnia = "niedziela"

        results.append({
            "date": dt,
            "day_name": dzien_tygodnia,
            "start": start,
            "end": end,
            "entries": wejscia,
        })

    return results


def pobierz_idw(dt: date):
    if dt >= GRANICA_IDW:
        return [23, 24]
    return [1, 17]


def pobierz_wolne(dt: date, godziny_wejsc, idw_list):
    date_string = dt.isoformat()
    wyniki = {}

    for idw in idw_list:
        try:
            response = requests.get(
                API_URL,
                params={
                    "ajax": "pobierzTerminy",
                    "selectedDate": date_string,
                    "idw": idw,
                    "idl": 0,
                    "idg": 0
                },
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            json_data = response.json()
        except requests.RequestException:
            continue
        except ValueError:
            continue

        if json_data.get("status") != "complete":
            continue

        for item in json_data.get("data", []):
            termin = str(item.get("terminGodzina", "")).strip()
            wolne = item.get("wolne")

            if termin in godziny_wejsc:
                wyniki[termin] = wolne

    return wyniki


@app.get("/", response_class=HTMLResponse)
def index():
    try:
        weekendy = pobierz_weekendowe_zmiany()
    except Exception as e:
        body = (
            '<h1 tabindex="-1" id="pageHeading">Moje tury</h1>'
            f'<p>{html.escape(str(e))}</p>'
        )
        return render_page("Błąd - Moje tury", body)

    if not weekendy:
        body = (
            '<h1 tabindex="-1" id="pageHeading">Moje tury</h1>'
            '<p>Brak nadchodzących weekendowych zmian w grafiku.</p>'
            '<script>document.getElementById("pageHeading").focus();</script>'
        )
        return render_page("Moje tury", body)

    options = []
    for idx, item in enumerate(weekendy):
        dt = item["date"]
        label = f'{item["day_name"]}, {dt.day} {MIESIACE[dt.month - 1]} {dt.year}, {item["start"]}–{item["end"]}'
        options.append(f'<option value="{idx}">{html.escape(label)}</option>')

    body = f"""
<h1>Moje tury</h1>

<form action="/wynik" method="get">
<label>Wybierz turę:<br>
<select name="idx" autofocus>
{''.join(options)}
</select>
</label>

<br><br>

<button type="submit">Sprawdź</button>
</form>
"""
    return render_page("Moje tury", body)


@app.get("/wynik", response_class=HTMLResponse)
def wynik(idx: int):
    try:
        weekendy = pobierz_weekendowe_zmiany()
    except Exception as e:
        body = (
            '<h1 tabindex="-1" id="pageHeading">Błąd</h1>'
            f'<p>{html.escape(str(e))}</p>'
            '<a class="button-link" href="/">Wróć do wyboru</a>'
            '<script>document.getElementById("pageHeading").focus();</script>'
        )
        return render_page("Błąd - Moje tury", body)

    if idx < 0 or idx >= len(weekendy):
        body = (
            '<h1 tabindex="-1" id="pageHeading">Nieprawidłowy wybór</h1>'
            '<p>Wybrana tura nie istnieje.</p>'
            '<a class="button-link" href="/">Wróć do wyboru</a>'
            '<script>document.getElementById("pageHeading").focus();</script>'
        )
        return render_page("Nieprawidłowy wybór - Moje tury", body)

    item = weekendy[idx]
    dt = item["date"]
    entries = item["entries"]

    if not entries:
        body = f"""
<h1 tabindex="-1" id="pageHeading">Wyniki dla {dt.day} {MIESIACE[dt.month - 1]} {dt.year}</h1>
<p>Nierozpoznany schemat zmiany: {html.escape(item["start"])}–{html.escape(item["end"])}</p>
<a class="button-link" href="/">Wróć do wyboru</a>
<script>document.getElementById("pageHeading").focus();</script>
"""
        return render_page("Wyniki - Moje tury", body)

    idw_list = pobierz_idw(dt)
    wolne_map = pobierz_wolne(dt, entries, idw_list)

    result_lines = []
    for godzina in entries:
        if godzina in wolne_map:
            result_lines.append(
                f'<p>Godzina {html.escape(godzina)}, {html.escape(str(wolne_map[godzina]))} wolnych</p>'
            )
        else:
            result_lines.append(
                f'<p>Godzina {html.escape(godzina)}, brak danych</p>'
            )

    body = f"""
<h1 tabindex="-1" id="pageHeading">Wyniki dla {dt.day} {MIESIACE[dt.month - 1]} {dt.year}</h1>
{''.join(result_lines)}
<a class="button-link" href="/">Wróć do wyboru</a>
<script>document.getElementById("pageHeading").focus();</script>
"""
    return render_page("Wyniki - Moje tury", body)
