# MESAU Hacks 3.0 — Human-Centered Design Brief

## Designing in Your Neighborhood

**Team members:** Shreya Bunga, Hugo Calderon Delgado, Andy Quach, Omar Ahmed, Michael-Eric Seijo  
**School:** California State University, East Bay  
**Project title:** Gas Station Locator — Fuel-aware trip planner

## Project description

*16 words (20-word maximum)*

Helps drivers plan fuel-aware trips by estimating range and comparing reachable refueling stops along a route.

## Neighborhood challenge

*66 words (75-word maximum)*

Commuters traveling to Cal State East Bay in Hayward often depend on personal vehicles, so fuel costs can add up alongside parking and other school expenses. AAA’s Oakland metro average for regular gas was $6.41 per gallon on September 27, 2026, compared with $4.63 a year earlier. Drivers also need a practical way to compare route detours, vehicle efficiency, and whether a station is safely reachable.

## Targeted user profile and needs

*66 words (75-word maximum)*

Our primary users are cost-conscious Cal State East Bay students, faculty, and staff who commute by car and want to make informed refueling choices without unnecessary detours.

- **Affordable:** Compare estimated station prices alongside detour distance—not price per gallon alone.
- **Efficient:** Find compatible options near the planned route and avoid unnecessary miles.
- **Confident:** Understand estimated fuel range and whether a stop is reachable while preserving a reserve.

## Proposed solution

*66 words (75-word maximum)*

Gas Station Locator takes a driver’s origin, destination, fuel type, current fuel, tank capacity, and MPG. It maps a driving route, estimates fuel needs, and ranks compatible nearby stations by estimated price, detour, and reachability while preserving a 10% tank reserve. The demo advances a simulated trip, reports refueling, updates estimates, and presents an arrival summary. Labeled controls and a responsive layout support use across devices.

## Success criteria

These are proposed pilot targets, not results already measured.

1. At least 4 out of 5 pilot drivers can identify whether and where to refuel within two minutes, without facilitator help.
2. In every tested scenario, recommended stops are within the estimated safe range while retaining the 10% tank reserve.
3. Pilot drivers rate their confidence in the refueling decision at least 4 out of 5 after using the planner.

## Coding integration

**Source code:** [github.com/0mar622/gas_station_locator](https://github.com/0mar622/gas_station_locator)

*70 words (75-word maximum)*

Python Flask serves the page and JSON APIs. It geocodes addresses, requests driving routes and distance matrices through HeiGIT/OpenRouteService, and reads station records from Firestore. The backend filters by fuel type, route proximity, and safe range, then ranks stops by estimated price and detour. JavaScript and Leaflet display the route and simulate progress and refueling. Active trips are saved in Firestore. This demo uses no live GPS or vehicle data.

## Future potential

*54 words (75-word maximum)*

After pilot testing, the prototype could connect to opt-in phone GPS or vehicle telemetry, use licensed live station prices, account for traffic and price freshness, and support saved vehicles and trips. Further development should add clear consent, privacy controls, secure account management, production monitoring, and testing with commuters before making savings or safety claims.

## Evidence and product notes

- AAA listed Oakland’s regular-gas average at **$6.4088/gal** on September 27, 2026, versus **$4.6310/gal** one year earlier; values above are rounded to cents. [AAA California fuel-price averages](https://gasprices.aaa.com/?state=CA)
- The application’s station prices are **synthetic estimates** based on California EIA weekly averages with a deterministic station-level adjustment. They are not live pump prices or AAA prices.
- The working demo uses a simulated route position and simulated refueling; it does not use GPS, vehicle telemetry, or an actual fuel transaction.
