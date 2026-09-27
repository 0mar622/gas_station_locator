# Alameda County synthetic gas-station sample

`alameda_county_gas_stations_synthetic_prices.csv` contains Alameda County OpenStreetMap gas-station objects, one row per OSM station and tagged fuel type. Names and coordinates are from OSM. Rows are included only when OSM has an explicit fuel-type tag; stations without a recognized fuel tag are omitted.

## Price fields

`price_usd_per_gallon` is synthetic, not a current pump quote. For regular, midgrade, premium, and diesel, the generator takes the latest California weekly average published by the U.S. Energy Information Administration and adds a deterministic random delta from −$1.000 to +$1.000 per gallon (seed 42). The source average, observation date, and applied delta are included in each priced row. Other fuel types have blank price fields because the EIA source table has no matching California retail average.

Regenerate the CSV from the repository root with:

```bash
uv run python server/services/build_station_dataset.py
```

The generator queries OpenStreetMap via the Overpass API for Alameda County and reads the EIA public weekly price table.

## Sources and attribution

- Station names, locations, and fuel tags: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
- Reference prices: [U.S. EIA California gasoline and diesel retail prices](https://www.eia.gov/dnav/pet/PET_PRI_GND_DCUS_SCA_W.htm), weekly statewide averages in dollars per gallon, including taxes.

The station data is a derived database from OSM and remains subject to ODbL attribution and share-alike terms. Synthetic prices must not be represented as observed station prices.
