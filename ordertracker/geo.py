"""Where your customers are, so the map and the clocks have something to plot.

Each country carries the position of its capital and its main IANA time-zone
name. The browser turns that name into a local time, so no time-zone database
is needed here and the clocks stay right through daylight saving changes.

A customer can always override the city, position and zone by hand; this list
only exists so that picking a country is enough to get started.
"""

# code | country | capital | latitude | longitude | IANA time zone
_TABLE = """
AE|United Arab Emirates|Abu Dhabi|24.47|54.37|Asia/Dubai
AR|Argentina|Buenos Aires|-34.60|-58.38|America/Argentina/Buenos_Aires
AT|Austria|Vienna|48.21|16.37|Europe/Vienna
AU|Australia|Canberra|-35.28|149.13|Australia/Sydney
BD|Bangladesh|Dhaka|23.81|90.41|Asia/Dhaka
BE|Belgium|Brussels|50.85|4.35|Europe/Brussels
BG|Bulgaria|Sofia|42.70|23.32|Europe/Sofia
BH|Bahrain|Manama|26.23|50.59|Asia/Bahrain
BR|Brazil|Brasilia|-15.79|-47.88|America/Sao_Paulo
BY|Belarus|Minsk|53.90|27.57|Europe/Minsk
CA|Canada|Ottawa|45.42|-75.70|America/Toronto
CH|Switzerland|Bern|46.95|7.45|Europe/Zurich
CL|Chile|Santiago|-33.45|-70.67|America/Santiago
CN|China|Beijing|39.90|116.41|Asia/Shanghai
CO|Colombia|Bogota|4.71|-74.07|America/Bogota
CR|Costa Rica|San Jose|9.93|-84.08|America/Costa_Rica
CZ|Czechia|Prague|50.08|14.44|Europe/Prague
DE|Germany|Berlin|52.52|13.40|Europe/Berlin
DK|Denmark|Copenhagen|55.68|12.57|Europe/Copenhagen
EE|Estonia|Tallinn|59.44|24.75|Europe/Tallinn
EG|Egypt|Cairo|30.04|31.24|Africa/Cairo
ES|Spain|Madrid|40.42|-3.70|Europe/Madrid
FI|Finland|Helsinki|60.17|24.94|Europe/Helsinki
FR|France|Paris|48.86|2.35|Europe/Paris
GB|United Kingdom|London|51.51|-0.13|Europe/London
GR|Greece|Athens|37.98|23.73|Europe/Athens
HK|Hong Kong|Hong Kong|22.32|114.17|Asia/Hong_Kong
HR|Croatia|Zagreb|45.81|15.98|Europe/Zagreb
HU|Hungary|Budapest|47.50|19.04|Europe/Budapest
ID|Indonesia|Jakarta|-6.21|106.85|Asia/Jakarta
IE|Ireland|Dublin|53.35|-6.26|Europe/Dublin
IL|Israel|Jerusalem|31.77|35.21|Asia/Jerusalem
IN|India|New Delhi|28.61|77.21|Asia/Kolkata
IR|Iran|Tehran|35.69|51.39|Asia/Tehran
IT|Italy|Rome|41.90|12.50|Europe/Rome
JP|Japan|Tokyo|35.68|139.69|Asia/Tokyo
KE|Kenya|Nairobi|-1.29|36.82|Africa/Nairobi
KH|Cambodia|Phnom Penh|11.56|104.92|Asia/Phnom_Penh
KR|South Korea|Seoul|37.57|126.98|Asia/Seoul
KW|Kuwait|Kuwait City|29.38|47.99|Asia/Kuwait
KZ|Kazakhstan|Astana|51.17|71.43|Asia/Almaty
LK|Sri Lanka|Colombo|6.93|79.86|Asia/Colombo
LT|Lithuania|Vilnius|54.69|25.28|Europe/Vilnius
LU|Luxembourg|Luxembourg|49.61|6.13|Europe/Luxembourg
LV|Latvia|Riga|56.95|24.11|Europe/Riga
MA|Morocco|Rabat|34.02|-6.84|Africa/Casablanca
MX|Mexico|Mexico City|19.43|-99.13|America/Mexico_City
MY|Malaysia|Kuala Lumpur|3.14|101.69|Asia/Kuala_Lumpur
NG|Nigeria|Abuja|9.06|7.49|Africa/Lagos
NL|Netherlands|Amsterdam|52.37|4.90|Europe/Amsterdam
NO|Norway|Oslo|59.91|10.75|Europe/Oslo
NZ|New Zealand|Wellington|-41.29|174.78|Pacific/Auckland
PE|Peru|Lima|-12.05|-77.04|America/Lima
PH|Philippines|Manila|14.60|120.98|Asia/Manila
PK|Pakistan|Islamabad|33.68|73.05|Asia/Karachi
PL|Poland|Warsaw|52.23|21.01|Europe/Warsaw
PT|Portugal|Lisbon|38.72|-9.14|Europe/Lisbon
QA|Qatar|Doha|25.29|51.53|Asia/Qatar
RO|Romania|Bucharest|44.43|26.10|Europe/Bucharest
RS|Serbia|Belgrade|44.79|20.45|Europe/Belgrade
RU|Russia|Moscow|55.76|37.62|Europe/Moscow
SA|Saudi Arabia|Riyadh|24.71|46.68|Asia/Riyadh
SE|Sweden|Stockholm|59.33|18.07|Europe/Stockholm
SG|Singapore|Singapore|1.35|103.82|Asia/Singapore
SI|Slovenia|Ljubljana|46.06|14.51|Europe/Ljubljana
SK|Slovakia|Bratislava|48.15|17.11|Europe/Bratislava
TH|Thailand|Bangkok|13.76|100.50|Asia/Bangkok
TR|Turkey|Ankara|39.93|32.86|Europe/Istanbul
TW|Taiwan|Taipei|25.03|121.57|Asia/Taipei
UA|Ukraine|Kyiv|50.45|30.52|Europe/Kyiv
US|United States|Washington DC|38.91|-77.04|America/New_York
UY|Uruguay|Montevideo|-34.90|-56.16|America/Montevideo
VN|Vietnam|Hanoi|21.03|105.85|Asia/Ho_Chi_Minh
ZA|South Africa|Pretoria|-25.75|28.19|Africa/Johannesburg
"""

# A handful of cities that matter more than their country's capital does for
# this trade, so "USA" does not always mean Washington.
_CITIES = """
US|San Jose|37.34|-121.89|America/Los_Angeles
US|Chicago|41.88|-87.63|America/Chicago
US|Austin|30.27|-97.74|America/Chicago
US|Boston|42.36|-71.06|America/New_York
CN|Shenzhen|22.54|114.06|Asia/Shanghai
CN|Shanghai|31.23|121.47|Asia/Shanghai
CN|Suzhou|31.30|120.59|Asia/Shanghai
KR|Incheon|37.46|126.71|Asia/Seoul
KR|Ansan|37.32|126.83|Asia/Seoul
KR|Daegu|35.87|128.60|Asia/Seoul
KR|Busan|35.18|129.08|Asia/Seoul
JP|Osaka|34.69|135.50|Asia/Tokyo
DE|Munich|48.14|11.58|Europe/Berlin
DE|Stuttgart|48.78|9.18|Europe/Berlin
VN|Ho Chi Minh City|10.82|106.63|Asia/Ho_Chi_Minh
IN|Bengaluru|12.97|77.59|Asia/Kolkata
"""


def _parse():
    countries, cities = {}, []
    for line in _TABLE.strip().splitlines():
        code, name, capital, lat, lon, tz = line.split("|")
        countries[code] = {
            "code": code, "name": name, "capital": capital,
            "lat": float(lat), "lon": float(lon), "timezone": tz,
        }
    for line in _CITIES.strip().splitlines():
        code, city, lat, lon, tz = line.split("|")
        cities.append({"country": code, "city": city, "lat": float(lat),
                       "lon": float(lon), "timezone": tz})
    return countries, cities


COUNTRIES, CITIES = _parse()


def country_list() -> list[dict]:
    """Every country, sorted by name, for the drop-down on the customer form."""
    return sorted(COUNTRIES.values(), key=lambda c: c["name"])


def city_list() -> list[dict]:
    return CITIES


def locate(country=None, city=None) -> dict | None:
    """Best known position for a country, or one of its named cities."""
    code = str(country or "").strip().upper()
    wanted = str(city or "").strip().lower()
    if wanted:
        for entry in CITIES:
            if entry["city"].lower() == wanted and (not code or entry["country"] == code):
                return {"country": entry["country"], "city": entry["city"],
                        "lat": entry["lat"], "lon": entry["lon"],
                        "timezone": entry["timezone"]}
    if code in COUNTRIES:
        found = COUNTRIES[code]
        return {"country": code, "city": city or found["capital"],
                "lat": found["lat"], "lon": found["lon"],
                "timezone": found["timezone"]}
    return None


def country_name(code) -> str:
    entry = COUNTRIES.get(str(code or "").strip().upper())
    return entry["name"] if entry else (code or "")
