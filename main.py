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

IDW_NORMALNE = 23
IDW_BEZ_DZIECI = 24
IDW_NORMALNE_STARE = 1
IDW_BEZ_DZIECI_STARE = 17


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
    line-height: 1.6;
    padding: 20px;
    max-width: 900px;
    margin: 0 auto;
}}
label {{
    display: block;
    margin-bottom: 10px;
}}
select, button {{
    font-size: 22px;
    padding: 10px;
    margin-top: 10px;
    max-width: 100%;
}}
button {{
    cursor: pointer;
}}
a.button-link {{
    display: inline-block;
    font-size: 22px;
    padding: 10px 14px;
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

    low = value.lower()
    if low in {"off", "l4"}:
        return low

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


def formatuj_date_pl(dt: date) -> str:
    return f"{dt.day} {MIESIACE[dt.month - 1]} {dt.year}"


def formatuj_ture(item: dict) -> str:
    dt = item["date"]
    return f'{item["day_name"]}, {formatuj_date_pl(dt)}, {item["start"]}–{item["end"]}'


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
        raise ValueError("Nie znaleziono wiersza Krzysztofa Tarasewicza.")

    for row in rows:
        found_blocks = 0
        for i in range(2, len(row), 3):
            dt = parse_date_cell(row[i] if i < len(row) else "")
            day_name = (row[i + 2] if i + 2 < len(row) else "").strip()
            if dt and day_name:
                found_blocks += 1
        if found_blocks >= 3:
            header_row = row
            break

    if header_row is None:
        raise ValueError("Nie znaleziono wiersza z datami.")

    return header_row, grafik_row


def pobierz_weekendowe_zmiany():
    rows = wczytaj_csv()
    header_row, grafik_row = znajdz_naglowek_i_wiersz_grafiku(rows)

    today = dzisiaj()
    results = []

    for i in range(2, len(header_row), 3):
        dt = parse_date_cell(header_row[i] if i < len(header_row) else "")
        if not dt:
            continue

        if dt < today:
            continue

        if dt.weekday() not in (5, 6):
            continue

        start_raw = grafik_row[i].strip() if i < len(grafik_row) and grafik_row[i] else ""
        end_raw = grafik_row[i + 1].strip() if i + 1 < len(grafik_row) and grafik_row[i + 1] else ""

        start = normalizuj_godzine(start_raw)
        end = normalizuj_godzine(end_raw)

        if start in {"off", "l4", ""} or end in {"off", "l4", ""}:
            continue

        if dt.weekday() == 5:
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


def pobierz_idw_typy(dt: date):
    if dt >= GRANICA_IDW:
        return {
            "normalne": IDW_NORMALNE,
            "bez dzieci": IDW_BEZ_DZIECI,
        }

    return {
        "normalne": IDW_NORMALNE_STARE,
        "bez dzieci": IDW_BEZ_DZIECI_STARE,
    }


def pobierz_wolne_dla_idw(dt: date, godziny_wejsc, idw: int):
    date_string = dt.isoformat()
    wyniki = {}

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
        return {}
    except ValueError:
        return {}

    if json_data.get("status") != "complete":
        return {}

    for item in json_data.get("data", []):
        termin = str(item.get("terminGodzina", "")).strip()
        wolne = item.get("wolne")

        if termin in godziny_wejsc:
            wyniki[termin] = wolne

    return wyniki


def pobierz_wolne(dt: date, godziny_wejsc):
    typy_idw = pobierz_idw_typy(dt)

    normalne_map = pobierz_wolne_dla_idw(dt, godziny_wejsc, typy_idw["normalne"])
    bez_dzieci_map = pobierz_wolne_dla_idw(dt, godziny_wejsc, typy_idw["bez dzieci"])

    wyniki = {}

    for godzina in godziny_wejsc:
        rekordy = []

        if godzina in normalne_map:
            rekordy.append({
                "typ": "normalne",
                "wolne": normalne_map[godzina],
            })

        if godzina in bez_dzieci_map:
            rekordy.append({
                "typ": "bez dzieci",
                "wolne": bez_dzieci_map[godzina],
            })

        wyniki[godzina] = rekordy

    return wyniki


@app.get("/", response_class=HTMLResponse)
def index():
    try:
        weekendy = pobierz_weekendowe_zmiany()
    except Exception as e:
        body = (
            '<h1 tabindex="-1" id="pageHeading">Moje tury</h1>'
            f'<p>{html.escape(str(e))}</p>'
            '<script>document.getElementById("pageHeading").focus();</script>'
        )
        return render_page("Błąd - Moje tury", body)

    if not weekendy:
        body = (
            '<h1 tabindex="-1" id="pageHeading">Moje tury</h1>'
            '<p>Brak weekendowych zmian.</p>'
            '<script>document.getElementById("pageHeading").focus();</script>'
        )
        return render_page("Moje tury", body)

    options = []
    for idx, item in enumerate(weekendy):
        label = formatuj_ture(item)
        options.append(f'<option value="{idx}">{html.escape(label)}</option>')

    body = f"""
<h1 tabindex="-1" id="pageHeading">Moje tury</h1>

<form action="/wynik" method="get">
<label for="idx">Wybierz turę:</label>
<select name="idx" id="idx" autofocus>
{''.join(options)}
</select>

<br><br>

<button type="submit">Sprawdź</button>
</form>

<script>document.getElementById("pageHeading").focus();</script>
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
            '<a class="button-link" href="/">Wróć</a>'
            '<script>document.getElementById("pageHeading").focus();</script>'
        )
        return render_page("Błąd - Moje tury", body)

    if idx < 0 or idx >= len(weekendy):
        body = (
            '<h1 tabindex="-1" id="pageHeading">Nieprawidłowy wybór</h1>'
            '<p>Wybrana tura nie istnieje.</p>'
            '<a class="button-link" href="/">Wróć</a>'
            '<script>document.getElementById("pageHeading").focus();</script>'
        )
        return render_page("Nieprawidłowy wybór - Moje tury", body)

    item = weekendy[idx]
    dt = item["date"]
    entries = item["entries"]
    opis_tury = formatuj_ture(item)

    if not entries:
        body = f"""
<h1 tabindex="-1" id="pageHeading">Wyniki</h1>
<p>{html.escape(opis_tury)}</p>
<p>Nierozpoznany schemat zmiany: {html.escape(item["start"])}–{html.escape(item["end"])}</p>
<a class="button-link" href="/">Wróć</a>
<script>document.getElementById("pageHeading").focus();</script>
"""
        return render_page("Wyniki - Moje tury", body)

    wolne_map = pobierz_wolne(dt, entries)

    result_lines = []
    ma_dane = False

    for godzina in entries:
        rekordy = wolne_map.get(godzina, [])

        if rekordy:
            ma_dane = True
            for rekord in rekordy:
                result_lines.append(
                    f'<p>{html.escape(godzina)}, {html.escape(rekord["typ"])}: {html.escape(str(rekord["wolne"]))} wolnych</p>'
                )
        else:
            result_lines.append(
                f'<p>{html.escape(godzina)}: brak danych</p>'
            )

    dodatkowy_komunikat = ""
    if not ma_dane:
        dodatkowy_komunikat = "<p>Brak danych z API.</p>"

    body = f"""
<h1 tabindex="-1" id="pageHeading">Wyniki</h1>
<p>{html.escape(opis_tury)}</p>
{dodatkowy_komunikat}
{''.join(result_lines)}
<a class="button-link" href="/">Wróć</a>
<script>document.getElementById("pageHeading").focus();</script>
"""
    return render_page("Wyniki - Moje tury", body)
