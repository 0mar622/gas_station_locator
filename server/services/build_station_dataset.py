"""Build a California gas-station CSV with clearly labeled synthetic prices."""

import csv
import random
from datetime import datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COUNTY_NAME = "Alameda County"
OUTPUT_FILE = PROJECT_ROOT / "data" / "alameda_county_gas_stations_synthetic_prices.csv"
EIA_URL = "https://www.eia.gov/dnav/pet/PET_PRI_GND_DCUS_SCA_W.htm"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
PRICE_DELTA_LIMIT = 1.00
RANDOM_SEED = 42

CSV_FIELDS = (
    "osm_id",
    "name",
    "latitude",
    "longitude",
    "fuel_type",
    "price_usd_per_gallon",
    "eia_reference_price",
    "synthetic_delta",
    "eia_date",
    "price_source",
    "osm_url",
)

PRICEABLE_TYPES = {"regular", "midgrade", "premium", "diesel"}


class EiaTableParser:
    """Read the latest observation from the EIA weekly California table."""

    def __init__(self):
        from html.parser import HTMLParser

        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.dates = []
                self.rows = []
                self._row_depth = 0
                self._current_row = None
                self._cell_class = None
                self._cell_text = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                classes = attrs.get("class", "").split()
                if tag == "tr":
                    if self._current_row is None and "DataRow" in classes:
                        self._current_row = {"label": "", "values": []}
                        self._row_depth = 1
                    elif self._current_row is not None:
                        self._row_depth += 1
                elif tag in ("th", "td") and classes:
                    if "Series5" in classes:
                        self._cell_class = "date"
                        self._cell_text = []
                    elif self._current_row is not None and (
                        "DataStub1" in classes
                        or "DataB" in classes
                        or "Current2" in classes
                    ):
                        self._cell_class = (
                            "label" if "DataStub1" in classes else "value"
                        )
                        self._cell_text = []

            def handle_data(self, data):
                if self._cell_class:
                    self._cell_text.append(data)

            def handle_endtag(self, tag):
                if tag in ("td", "th") and self._cell_class:
                    value = " ".join("".join(self._cell_text).split())
                    if self._cell_class == "date":
                        self.dates.append(value)
                    elif self._cell_class == "label":
                        self._current_row["label"] = value
                    elif self._cell_class == "value":
                        self._current_row["values"].append(value)
                    self._cell_class = None
                    self._cell_text = []
                elif tag == "tr" and self._current_row is not None:
                    self._row_depth -= 1
                    if self._row_depth == 0:
                        self.rows.append(self._current_row)
                        self._current_row = None

        self._parser = Parser()

    def feed(self, document):
        self._parser.feed(document)
        return self._parser


def fetch_eia_prices(session):
    response = session.get(EIA_URL, timeout=30)
    response.raise_for_status()
    parser = EiaTableParser().feed(response.text)

    observations = {}
    wanted = {
        "Regular": "regular",
        "Midgrade": "midgrade",
        "Premium": "premium",
        "Diesel (On-Highway) - All Types": "diesel",
    }
    date_values = []
    for raw_date in parser.dates:
        try:
            date_values.append(datetime.strptime(raw_date, "%m/%d/%y").date())
        except ValueError:
            date_values.append(None)

    if not date_values:
        raise RuntimeError("Could not find observation dates in the EIA table")

    for row in parser.rows:
        fuel_type = wanted.get(row["label"])
        if not fuel_type:
            continue
        for observation_date, raw_price in zip(date_values, row["values"]):
            if observation_date is None:
                continue
            try:
                price = float(raw_price.replace(",", ""))
            except (TypeError, ValueError):
                continue
            prior = observations.get(fuel_type)
            if prior is None or observation_date.isoformat() > prior["date"]:
                observations[fuel_type] = {
                    "price": price,
                    "date": observation_date.isoformat(),
                }

    missing = PRICEABLE_TYPES - observations.keys()
    if missing:
        raise RuntimeError(
            "Could not parse EIA prices for: " + ", ".join(sorted(missing))
        )
    dates = {entry["date"] for entry in observations.values()}
    if len(dates) != 1:
        raise RuntimeError("EIA fuel-grade observations have inconsistent dates")
    return observations


def fetch_osm_stations(session):
    query = f"""[out:json][timeout:60];
area["name"="{COUNTY_NAME}"]["admin_level"="6"]->.target_area;
(
  node["amenity"="fuel"](area.target_area);
  way["amenity"="fuel"](area.target_area);
  relation["amenity"="fuel"](area.target_area);
);
out center tags;"""
    errors = []
    for endpoint in OVERPASS_URLS:
        try:
            response = session.post(
                endpoint,
                data={"data": query},
                headers={"Accept": "application/json"},
                timeout=(15, 150),
            )
            response.raise_for_status()
            elements = response.json().get("elements", [])
            if not elements:
                raise RuntimeError("OSM query returned no gas stations")
            return elements
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            errors.append(f"{endpoint}: {exc}")
    raise RuntimeError("All Overpass endpoints failed:\n" + "\n".join(errors))


def enabled(value):
    return str(value).strip().lower() not in {"", "no", "false", "0", "none"}


def normalize_fuels(tags):
    fuels = set()
    for key, value in tags.items():
        if not key.startswith("fuel:") or not enabled(value):
            continue
        subtype = key.split(":", 1)[1].lower()
        if subtype == "diesel" or subtype.endswith("_diesel"):
            fuels.add("diesel")
        elif subtype in {"unleaded", "gasoline", "petrol"}:
            fuels.add("regular")
        elif subtype.startswith("octane_"):
            try:
                octane = int(subtype.removeprefix("octane_"))
            except ValueError:
                fuels.add(subtype.replace("_", " "))
            else:
                fuels.add("regular" if octane <= 87 else "midgrade" if octane <= 89 else "premium")
        elif subtype in {"e10", "e15"}:
            fuels.add(subtype)
        elif subtype in {"e85", "e100", "lpg", "cng", "lng", "hydrogen", "propane"}:
            fuels.add(subtype)
        else:
            fuels.add(subtype.replace("_", " "))
    return sorted(fuels) or ["unknown"]


def element_location(element):
    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"]
    center = element.get("center", {})
    if "lat" in center and "lon" in center:
        return center["lat"], center["lon"]
    return None


def station_rows(elements, eia_prices, seed=RANDOM_SEED):
    rng = random.Random(seed)
    elements = sorted(elements, key=lambda item: (item["type"], item["id"]))
    for element in elements:
        location = element_location(element)
        if location is None:
            continue
        tags = element.get("tags", {})
        name = tags.get("name") or tags.get("brand") or "(unnamed)"
        osm_kind = element["type"]
        osm_id = f"{osm_kind}/{element['id']}"
        for fuel_type in normalize_fuels(tags):
            if fuel_type == "unknown":
                continue
            price_data = eia_prices.get(fuel_type) if fuel_type in PRICEABLE_TYPES else None
            if price_data:
                delta = round(rng.uniform(-PRICE_DELTA_LIMIT, PRICE_DELTA_LIMIT), 3)
                price = round(price_data["price"] + delta, 3)
                reference_price = f"{price_data['price']:.3f}"
                price = f"{price:.3f}"
                delta = f"{delta:+.3f}"
                eia_date = price_data["date"]
                price_source = "synthetic_from_eia"
            else:
                price = reference_price = delta = eia_date = ""
                price_source = "unavailable"
            yield {
                "osm_id": osm_id,
                "name": name,
                "latitude": f"{location[0]:.7f}",
                "longitude": f"{location[1]:.7f}",
                "fuel_type": fuel_type,
                "price_usd_per_gallon": price,
                "eia_reference_price": reference_price,
                "synthetic_delta": delta,
                "eia_date": eia_date,
                "price_source": price_source,
                "osm_url": f"https://www.openstreetmap.org/{osm_id}",
            }


def write_csv(rows, output_file=OUTPUT_FILE):
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": "gas-station-locator-dataset/0.1"})
    eia_prices = fetch_eia_prices(session)
    stations = fetch_osm_stations(session)
    rows = list(station_rows(stations, eia_prices))
    write_csv(rows)
    print(f"Wrote {len(rows):,} station/fuel rows for {COUNTY_NAME} to {OUTPUT_FILE}")
    print(f"Unique OSM station records: {len({row['osm_id'] for row in rows}):,}")
    print("EIA baselines:")
    for fuel_type in sorted(eia_prices):
        entry = eia_prices[fuel_type]
        print(f"  {fuel_type}: ${entry['price']:.3f}/gal ({entry['date']})")
    print("Prices are synthetic: EIA baseline plus a seeded random delta within ±$1.000/gal.")


if __name__ == "__main__":
    main()
