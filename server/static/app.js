const form = document.getElementById('trip-form');
const statusBox = document.getElementById('status');
const stationsList = document.getElementById('stations-list');
const routeMapElement = document.getElementById('route-map');
const warningBox = document.getElementById('warning-box');
const timelineElement = document.getElementById('trip-timeline');

const field = (name) => form.elements[name];
const element = (id) => document.getElementById(id);
const show = (id, visible) => { element(id).hidden = !visible; };

const demo = {
  phase: 'form',
  preview: null,
  trip: null,
  token: null,
  totalDistanceMiles: 0,
  destinationLabel: '',
  progressMiles: 0,
  routeCoordinates: [],
  routeMeasure: [],
  startFuelGallons: 0,
  refueledGallons: 0,
  refuelCostEstimate: 0,
  didRefuel: false,
  atStop: false,
  stopStation: null,
  busy: false,
  lastObservedMs: 0,
  pendingProgress: null,
  pendingRefuelGallons: null,
  timeline: [],
};

let map = null;
let routeLine = null;
let stationLayer = null;
let endpointLayer = null;
let vehicleMarker = null;

const escapeHtml = (value) => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');

const setStatus = (message, type = '') => {
  statusBox.textContent = message;
  statusBox.className = `status ${type}`.trim();
  element('active-status').textContent = message;
  element('active-status').className = `status ${type}`.trim();
};

const setBusy = (busy) => {
  demo.busy = busy;
  form.querySelector('button[type="submit"]').disabled = busy;
  ['start-demo', 'next-step', 'stop-refuel', 'reset-demo'].forEach((id) => {
    element(id).disabled = busy;
  });
};

const numericField = (name) => {
  const value = Number(field(name).value);
  if (!Number.isFinite(value)) throw new Error(`Enter a valid ${name.replaceAll('_', ' ')}.`);
  return value;
};

const tripInput = (includeCapacity = false) => {
  const fuel = numericField('current_fuel_gallons');
  const capacity = numericField('fuel_capacity_gallons');
  const mpg = numericField('vehicle_mpg');
  if (fuel < 0 || fuel > capacity) throw new Error('Current fuel must be between zero and tank capacity.');
  if (capacity <= 0 || mpg <= 0) throw new Error('Tank capacity and MPG must be greater than zero.');

  const payload = {
    starting_location: field('starting_location').value.trim(),
    destination: field('destination').value.trim(),
    fuel_type: field('fuel_type').value,
    current_fuel_gallons: fuel,
    vehicle_mpg: mpg,
  };
  if (includeCapacity) payload.tank_capacity_gallons = capacity;
  return payload;
};

const requestJson = async (url, options = {}) => {
  const response = await fetch(url, options);
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error('The server returned an unreadable response. Try again.');
  }
  if (!response.ok) {
    const error = new Error(result.error || 'The trip request failed.');
    error.status = response.status;
    throw error;
  }
  return result;
};

const formatNumber = (value, digits = 1) => {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : '—';
};

const shortDestinationLabel = () => (
  /\bSFO\b|San Francisco International Airport/i.test(demo.destinationLabel)
    ? 'SFO'
    : demo.destinationLabel || 'destination'
);

const setMetric = (labelId, valueId, label, value) => {
  element(labelId).textContent = label;
  element(valueId).textContent = value;
};

const renderWarning = (trip) => {
  const messages = [];
  if (trip?.warning) messages.push(trip.warning);
  if (trip?.station_status === 'no_safe_station' && !trip.warning) {
    messages.push('No station is currently reachable while preserving the 10% fuel reserve.');
  }
  if (trip?.station_status === 'unavailable' && !trip.warning) {
    messages.push('Station recommendations are temporarily unavailable.');
  }
  warningBox.textContent = messages.join(' ');
  warningBox.style.display = messages.length ? 'block' : 'none';
};

const renderStations = (stations, active = false) => {
  if (!Array.isArray(stations) || stations.length === 0) {
    const message = active && demo.trip?.station_status === 'no_safe_station'
      ? 'No reachable station found for this fuel level.'
      : 'No gas stations found for this route.';
    stationsList.innerHTML = `<div class="station-card"><h3>${message}</h3><div class="station-meta"><span>Recommendations update as the simulated trip advances.</span></div></div>`;
    return;
  }

  stationsList.innerHTML = stations.map((station, index) => {
    const name = escapeHtml(station.name || 'Unnamed station');
    const price = station.price != null ? `$${formatNumber(station.price, 2)}/gal` : 'Price unavailable';
    const offRoute = station.distance_to_route_miles != null
      ? `${formatNumber(station.distance_to_route_miles)} mi off route`
      : 'Distance unavailable';
    const drive = station.driving_distance_miles != null
      ? `${formatNumber(station.driving_distance_miles)} mi drive`
      : null;
    const routeProgress = station.route_progress_miles != null
      ? `Route position: ${formatNumber(station.route_progress_miles)} mi`
      : null;
    const fuelType = station.fuel_type ? escapeHtml(station.fuel_type.toUpperCase()) : 'Fuel';
    const reachable = station.within_safe_range === true;
    const isSelectedStop = active && reachable && demo.stopStation
      ? station.id === demo.stopStation.id
      : active && index === 0 && reachable;
    const badge = isSelectedStop
      ? `<strong>${demo.stopStation ? 'Recommended refuel stop' : 'Top reachable recommendation'}</strong>`
      : '';
    const meta = [fuelType, offRoute, drive, routeProgress].filter(Boolean)
      .map((item) => `<span>${item}</span>`).join('');

    return `
      <div class="station-card ${isSelectedStop ? 'recommended' : ''}">
        ${badge ? `<div class="station-meta">${badge}</div>` : ''}
        <h3>${name}</h3>
        <div class="station-meta">${meta}</div>
        <div class="station-price">${price}</div>
      </div>
    `;
  }).join('');
};

const renderTimeline = () => {
  timelineElement.replaceChildren();
  demo.timeline.forEach((entry) => {
    const item = document.createElement('li');
    item.textContent = entry;
    timelineElement.append(item);
  });
  timelineElement.style.display = demo.timeline.length ? 'block' : 'none';
};

const addTimeline = (message) => {
  demo.timeline.push(message);
  renderTimeline();
};

const renderSummary = (data, mode) => {
  if (mode === 'preview') {
    element('cost-note').hidden = true;
    element('trip-title').textContent = 'Trip preview';
    element('trip-subtitle').textContent = 'Review the route and station candidates before starting.';
    element('range-label').textContent = 'Estimated range';
    setMetric('distance-label', 'distance-value', 'Trip distance', `${formatNumber(data.distance_miles)} mi`);
    setMetric('duration-label', 'duration-value', 'Estimated duration', `${formatNumber(data.duration_minutes)} min`);
    setMetric('fuel-label', 'fuel-value', 'Starting fuel', `${formatNumber(field('current_fuel_gallons').value)} gal`);
    element('range-value').textContent = `${formatNumber(data.estimated_range_miles)} mi`;
  } else {
    const completed = mode === 'completed';
    element('trip-title').textContent = completed ? `Arrived at ${shortDestinationLabel()}` : 'Simulated trip in progress';
    element('trip-subtitle').textContent = completed
      ? 'Trip complete. All figures are estimates from the simulated drive.'
      : `Use Next step to advance along the route to ${shortDestinationLabel()}. Safe range keeps a 10% tank reserve; location is simulated.`;
    setMetric(
      'distance-label',
      'distance-value',
      completed ? 'Distance traveled' : 'Miles remaining',
      `${formatNumber(completed ? data.distance_traveled_miles : data.route_miles_remaining)} mi`,
    );
    setMetric(
      'duration-label',
      'duration-value',
      completed ? 'Estimated fuel used' : 'Fuel needed for route',
      completed
        ? `${formatNumber(demo.startFuelGallons + demo.refueledGallons - Number(data.fuel_remaining_gallons))} gal`
        : `${formatNumber(data.fuel_needed_gallons)} gal`,
    );
    setMetric('fuel-label', 'fuel-value', 'Fuel remaining (estimated)', `${formatNumber(data.fuel_remaining_gallons)} gal`);
    element('range-label').textContent = completed ? 'Safe range at arrival' : 'Safe range (10% reserve)';
    element('range-value').textContent = `${formatNumber(data.safe_range_miles)} mi`;
    element('trip-subtitle').textContent += ` ${data.price_note || ''}`;
    const costNote = element('cost-note');
    if (completed) {
      costNote.textContent = demo.refuelCostEstimate > 0
        ? `Simulated refuel estimate: $${formatNumber(demo.refuelCostEstimate, 2)} using the station's estimated price; not a live receipt.`
        : 'No simulated fuel purchase was recorded. Station prices are estimates, not live pump prices.';
    } else {
      const cost = data.estimated_additional_purchase_cost_usd;
      costNote.textContent = cost == null
        ? 'Additional fuel cost estimate is unavailable until a reachable station is found.'
        : `Estimated additional fuel cost: $${formatNumber(cost, 2)}. ${data.cost_price_assumption || ''}`;
    }
    costNote.hidden = false;
  }
};

const renderControls = () => {
  const previewed = demo.phase === 'preview';
  const active = demo.phase === 'active';
  const completed = demo.phase === 'completed';
  show('start-demo', previewed);
  show('next-step', active && !demo.atStop);
  show('stop-refuel', active && demo.atStop);
  show('reset-demo', completed || previewed);
  show('demo-badge', active || completed);
  form.hidden = active || completed;
  element('active-panel').hidden = !active && !completed;
  if (active) {
    const fuel = `${formatNumber(demo.trip.fuel_remaining_gallons)} gal`;
    const remaining = `${formatNumber(demo.trip.route_miles_remaining)} mi`;
    element('active-panel-copy').textContent = demo.atStop
      ? `At the simulated stop${demo.stopStation?.name ? `: ${demo.stopStation.name}` : ''}. Report the refuel to continue.`
      : `Current estimate: ${fuel} remaining, ${remaining} to ${shortDestinationLabel()}.`;
  } else if (completed) {
    element('active-panel-copy').textContent = 'The simulated trip is complete. Start a new demo to run it again.';
  }
};

const renderTrip = (data, mode) => {
  renderSummary(data, mode);
  renderWarning(data);
  renderStations(data.stations, mode === 'active');
  renderTimeline();
  renderControls();
};

const haversineMiles = (a, b) => {
  const radians = (degrees) => degrees * Math.PI / 180;
  const latitudeDelta = radians(b[1] - a[1]);
  const longitudeDelta = radians(b[0] - a[0]);
  const firstLatitude = radians(a[1]);
  const secondLatitude = radians(b[1]);
  const value = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(firstLatitude) * Math.cos(secondLatitude) * Math.sin(longitudeDelta / 2) ** 2;
  return 3958.7613 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
};

const setRouteMeasure = (route) => {
  const coordinates = route?.features?.[0]?.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) {
    throw new Error('The route did not include enough geometry to simulate progress.');
  }
  demo.routeCoordinates = coordinates
    .filter((point) => Array.isArray(point) && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])))
    .map((point) => [Number(point[0]), Number(point[1])]);
  if (demo.routeCoordinates.length < 2) throw new Error('The route geometry is invalid.');

  demo.routeMeasure = [0];
  for (let index = 1; index < demo.routeCoordinates.length; index += 1) {
    demo.routeMeasure.push(demo.routeMeasure[index - 1]
      + haversineMiles(demo.routeCoordinates[index - 1], demo.routeCoordinates[index]));
  }
  if (!Number.isFinite(demo.totalDistanceMiles) || demo.totalDistanceMiles <= 0) {
    throw new Error('The trip did not include a valid route distance for simulation.');
  }
};

const coordinateAtProgress = (miles) => {
  const totalGeometryMiles = demo.routeMeasure.at(-1);
  const target = totalGeometryMiles * Math.max(0, Math.min(1, miles / demo.totalDistanceMiles));
  let index = demo.routeMeasure.findIndex((distance) => distance >= target);
  if (index <= 0) return demo.routeCoordinates[0];
  if (index < 0) return demo.routeCoordinates.at(-1);
  const segmentStart = demo.routeMeasure[index - 1];
  const segmentLength = demo.routeMeasure[index] - segmentStart;
  const ratio = segmentLength > 0 ? (target - segmentStart) / segmentLength : 0;
  const from = demo.routeCoordinates[index - 1];
  const to = demo.routeCoordinates[index];
  return [from[0] + (to[0] - from[0]) * ratio, from[1] + (to[1] - from[1]) * ratio];
};

const toLatLngs = (coordinates) => coordinates.map(([longitude, latitude]) => [latitude, longitude]);

const ensureMap = () => {
  if (map) return;
  if (!window.L) {
    routeMapElement.textContent = 'The map library could not load. Check the demo internet connection.';
    return;
  }
  map = L.map(routeMapElement).setView([37.6, -122.2], 9);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
  routeLine = L.polyline([], { color: '#2563eb', weight: 5, opacity: 0.85 }).addTo(map);
  stationLayer = L.layerGroup().addTo(map);
  endpointLayer = L.layerGroup().addTo(map);
};

const renderMap = (data, { fit = false } = {}) => {
  ensureMap();
  if (!map) return;

  const route = data?.route;
  const coordinates = route?.features?.[0]?.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) return;
  const points = coordinates.map(([longitude, latitude]) => [Number(latitude), Number(longitude)]);
  routeLine.setLatLngs(points);

  stationLayer.clearLayers();
  (data.stations || []).forEach((station, index) => {
    const latitude = Number(station.latitude);
    const longitude = Number(station.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    const name = escapeHtml(station.name || `Station ${index + 1}`);
    const price = station.price != null ? `$${formatNumber(station.price, 2)}/gal` : 'Price unavailable';
    const selectedStop = demo.stopStation && station.id === demo.stopStation.id;
    const primaryMarker = selectedStop || (index === 0 && demo.phase === 'active' && !demo.stopStation);
    const marker = L.circleMarker([latitude, longitude], {
      radius: primaryMarker ? 9 : 7,
      color: '#ffffff',
      weight: 2,
      fillColor: primaryMarker ? '#1d4ed8' : '#0f766e',
      fillOpacity: 1,
    }).addTo(stationLayer);
    marker.bindPopup(`<strong>${name}</strong><br>${price}`);
  });

  endpointLayer.clearLayers();
  const start = data.origin;
  const endpoint = points.at(-1);
  if (start && Number.isFinite(Number(start.latitude)) && Number.isFinite(Number(start.longitude))) {
    L.circleMarker([Number(start.latitude), Number(start.longitude)], {
      radius: 7, color: '#fff', weight: 2, fillColor: '#15803d', fillOpacity: 1,
    }).bindTooltip('Start').addTo(endpointLayer);
  }
  L.circleMarker(endpoint, {
    radius: 7, color: '#fff', weight: 2, fillColor: '#b91c1c', fillOpacity: 1,
  }).bindTooltip('Destination').addTo(endpointLayer);

  if (demo.phase === 'active' || demo.phase === 'completed') {
    const current = data.current_location;
    const simulatedPoint = current
      ? [Number(current.latitude), Number(current.longitude)]
      : toLatLngs([coordinateAtProgress(demo.progressMiles)])[0];
    const icon = L.divIcon({
      className: '',
      html: '<div class="vehicle-marker" aria-label="Simulated vehicle">●</div>',
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    });
    if (vehicleMarker) vehicleMarker.setLatLng(simulatedPoint).setIcon(icon);
    else vehicleMarker = L.marker(simulatedPoint, { icon, zIndexOffset: 1000 }).addTo(map);
  } else if (vehicleMarker) {
    map.removeLayer(vehicleMarker);
    vehicleMarker = null;
  }

  if (fit) map.fitBounds(routeLine.getBounds(), { padding: [20, 20] });
  else if (vehicleMarker) map.panTo(vehicleMarker.getLatLng(), { animate: true, duration: 0.35 });
  window.setTimeout(() => map.invalidateSize(), 0);
};

const findNextStop = () => {
  const needFuel = Number(demo.trip?.additional_gallons_needed) > 0.05;
  if (!needFuel || demo.didRefuel || demo.trip?.station_status !== 'recommended') return null;
  const stations = Array.isArray(demo.trip.stations) ? demo.trip.stations : [];
  return stations.find((station) => (
    station.within_safe_range === true
    && Number.isFinite(Number(station.route_progress_miles))
    && Number(station.route_progress_miles) > demo.progressMiles + 0.5
  )) || null;
};

const renderActiveState = (response) => {
  demo.trip = response;
  if (Number.isFinite(Number(response.route_miles_remaining))) {
    demo.progressMiles = Math.max(0, demo.totalDistanceMiles - Number(response.route_miles_remaining));
  }
  demo.stopStation = findNextStop();
  renderTrip(response, response.status === 'completed' ? 'completed' : 'active');
  renderMap(response);
};

const createProgressBody = (coordinate, gallonsAdded = null) => {
  const serverTime = Date.parse(demo.trip?.last_update_at || '');
  const timestamp = Math.max(Date.now(), Number.isFinite(serverTime) ? serverTime + 1000 : 0, demo.lastObservedMs + 1000);
  demo.lastObservedMs = timestamp;
  const body = {
    update_id: window.crypto?.randomUUID?.() || `demo-${timestamp}-${Math.random().toString(16).slice(2)}`,
    observed_at: new Date(timestamp).toISOString(),
    latitude: coordinate[1],
    longitude: coordinate[0],
    accuracy_meters: 5,
  };
  if (gallonsAdded != null) body.gallons_added = gallonsAdded;
  return body;
};

const sendProgress = async (coordinate, gallonsAdded = null) => {
  const body = demo.pendingProgress || createProgressBody(coordinate, gallonsAdded);
  try {
    const response = await requestJson(`/trip/${encodeURIComponent(demo.trip.trip_id)}/progress`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${demo.token}`,
      },
      body: JSON.stringify(body),
    });
    demo.pendingProgress = null;
    return response;
  } catch (error) {
    if (!error.status || error.status >= 500) {
      // Retry an uncertain write with the same ID and exact body to avoid double-counting fuel.
      demo.pendingProgress = body;
    } else if (error.status === 409) {
      demo.pendingProgress = null;
      const latest = await requestJson(`/trip/${encodeURIComponent(demo.trip.trip_id)}`, {
        headers: { Authorization: `Bearer ${demo.token}` },
      });
      renderActiveState(latest);
      error.message = 'Trip state changed elsewhere. It has been refreshed; try the next step again.';
    }
    throw error;
  }
};

const handlePlan = async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  try {
    const payload = tripInput();
    setBusy(true);
    setStatus('Planning route and finding nearby stations…');
    const result = await requestJson('/trip/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    demo.phase = 'preview';
    demo.preview = result;
    demo.trip = null;
    demo.timeline = [];
    renderTrip(result, 'preview');
    renderMap(result, { fit: true });
    setStatus('Trip preview ready. Start the simulated trip when you are ready.', 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    setBusy(false);
  }
};

const handleStart = async () => {
  try {
    const payload = tripInput(true);
    setBusy(true);
    setStatus('Starting and saving the demo trip…');
    const trip = await requestJson('/trip/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!trip.trip_id || !trip.access_token) throw new Error('The server did not return trip credentials.');

    demo.phase = 'active';
    demo.trip = trip;
    demo.token = trip.access_token;
    demo.destinationLabel = trip.destination || field('destination').value.trim();
    demo.totalDistanceMiles = Number(trip.route_miles_remaining);
    demo.progressMiles = 0;
    demo.startFuelGallons = Number(trip.fuel_remaining_gallons);
    demo.refueledGallons = 0;
    demo.refuelCostEstimate = 0;
    demo.didRefuel = false;
    demo.atStop = false;
    demo.lastObservedMs = 0;
    setRouteMeasure(trip.route);
    const start = trip.current_location;
    if (start) {
      demo.timeline = [`Started at ${trip.origin?.label || 'CSUEB (Hayward)'}. Location is simulated.`];
    }
    renderActiveState(trip);
    setStatus('Demo trip started. Use Next step to move along the route.', 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    setBusy(false);
  }
};

const advanceToDestination = async () => {
  const destination = demo.routeCoordinates.at(-1);
  let response = await sendProgress(destination);
  demo.progressMiles = demo.totalDistanceMiles;
  renderActiveState(response);
  if (response.status !== 'completed') {
    response = await sendProgress(destination);
    renderActiveState(response);
  }
  if (response.status === 'completed') {
    demo.phase = 'completed';
    addTimeline(`Arrived at ${shortDestinationLabel()}. The active trip is complete.`);
    renderTrip(response, 'completed');
    renderMap(response);
    setStatus(`Arrived at ${shortDestinationLabel()}. Demo trip complete.`, 'success');
  } else {
    setStatus('The destination update was accepted, but the backend has not marked the trip complete yet. Try Next step again.', '');
  }
};

const handleNext = async () => {
  if (!demo.trip || demo.busy) return;
  try {
    setBusy(true);
    const station = findNextStop();
    const stationProgress = station ? Number(station.route_progress_miles) : null;
    const targetProgress = stationProgress != null
      ? Math.min(demo.progressMiles + 5, stationProgress)
      : Math.min(demo.progressMiles + 6, demo.totalDistanceMiles);

    if (targetProgress >= demo.totalDistanceMiles - 0.15) {
      setStatus(`Advancing to ${shortDestinationLabel()}…`);
      await advanceToDestination();
      return;
    }

    setStatus(station && targetProgress >= stationProgress - 0.05
      ? `Advancing to recommended stop: ${station.name || 'gas station'}…`
      : 'Advancing along the simulated route…');
    const coordinate = coordinateAtProgress(targetProgress);
    const response = await sendProgress(coordinate);
    renderActiveState(response);

    if (station && targetProgress >= stationProgress - 0.05 && Number(response.additional_gallons_needed) > 0.05) {
      demo.atStop = true;
      demo.stopStation = station;
      addTimeline(`Reached recommended stop: ${station.name || 'gas station'} (simulated).`);
      renderTrip(response, 'active');
      renderMap(response);
      setStatus('At the recommended stop. Report a simulated refuel to continue.', 'success');
    } else {
      addTimeline(`Advanced to ${formatNumber(demo.progressMiles)} mi on the route (simulated).`);
      setStatus('Trip progress updated.', 'success');
    }
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    setBusy(false);
  }
};

const handleRefuel = async () => {
  if (!demo.trip || !demo.atStop || demo.busy) return;
  try {
    const capacity = Number(demo.trip.tank_capacity_gallons);
    const currentFuel = Number(demo.trip.fuel_remaining_gallons);
    const targetFuel = capacity * 0.75;
    const gallonsAdded = demo.pendingRefuelGallons
      ?? Math.round(Math.max(0.1, targetFuel - currentFuel) * 10) / 10;
    if (currentFuel + gallonsAdded > capacity) throw new Error('The simulated refuel would exceed tank capacity.');

    setBusy(true);
    demo.pendingRefuelGallons = gallonsAdded;
    setStatus(`Reporting ${formatNumber(gallonsAdded)} gallons added…`);
    const coordinate = demo.routeCoordinates.length
      ? coordinateAtProgress(demo.progressMiles)
      : [demo.trip.current_location.longitude, demo.trip.current_location.latitude];
    const response = await sendProgress(coordinate, gallonsAdded);
    if (response.update_status === 'accepted' || response.update_status === 'duplicate') {
      demo.refueledGallons += gallonsAdded;
      const stationPrice = Number(demo.stopStation?.price);
      if (Number.isFinite(stationPrice)) demo.refuelCostEstimate += gallonsAdded * stationPrice;
    } else {
      renderActiveState(response);
      demo.atStop = true;
      demo.pendingRefuelGallons = null;
      demo.stopStation = demo.stopStation || findNextStop();
      renderControls();
      throw new Error('The refuel update was stale and was not applied. Please try again.');
    }
    demo.didRefuel = true;
    demo.atStop = false;
    demo.pendingRefuelGallons = null;
    const stopName = demo.stopStation?.name || 'recommended gas station';
    demo.phase = response.status === 'completed' ? 'completed' : 'active';
    renderActiveState(response);
    addTimeline(`Refueled at ${stopName}: ${formatNumber(gallonsAdded)} gal added (simulated).`);
    setStatus(`Fuel estimate updated. Continue toward ${shortDestinationLabel()} with Next step.`, 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    setBusy(false);
  }
};

const resetDemo = () => {
  demo.phase = 'form';
  demo.preview = null;
  demo.trip = null;
  demo.token = null;
  demo.totalDistanceMiles = 0;
  demo.destinationLabel = '';
  demo.progressMiles = 0;
  demo.routeCoordinates = [];
  demo.routeMeasure = [];
  demo.startFuelGallons = 0;
  demo.refueledGallons = 0;
  demo.refuelCostEstimate = 0;
  demo.didRefuel = false;
  demo.atStop = false;
  demo.stopStation = null;
  demo.pendingProgress = null;
  demo.pendingRefuelGallons = null;
  demo.timeline = [];
  if (map) {
    routeLine.setLatLngs([]);
    stationLayer.clearLayers();
    endpointLayer.clearLayers();
    if (vehicleMarker) map.removeLayer(vehicleMarker);
    vehicleMarker = null;
  }
  stationsList.replaceChildren();
  warningBox.style.display = 'none';
  element('trip-title').textContent = 'Trip preview';
  element('trip-subtitle').textContent = 'Preview the route and stations before starting the demo.';
  element('range-label').textContent = 'Range';
  setMetric('distance-label', 'distance-value', 'Distance', '—');
  setMetric('duration-label', 'duration-value', 'Duration', '—');
  setMetric('fuel-label', 'fuel-value', 'Fuel left', '—');
  element('range-value').textContent = '—';
  element('distance-value').textContent = '—';
  element('duration-value').textContent = '—';
  element('fuel-value').textContent = '—';
  element('cost-note').hidden = true;
  timelineElement.replaceChildren();
  renderControls();
  setStatus('Ready to plan.', '');
};

form.addEventListener('submit', handlePlan);
form.addEventListener('input', () => {
  if (demo.phase === 'preview') {
    demo.phase = 'form';
    demo.preview = null;
    renderControls();
    setStatus('Trip details changed. Plan again to refresh the preview.', '');
  }
});
form.addEventListener('change', () => {
  if (demo.phase === 'preview') {
    demo.phase = 'form';
    demo.preview = null;
    renderControls();
    setStatus('Trip details changed. Plan again to refresh the preview.', '');
  }
});
element('start-demo').addEventListener('click', handleStart);
element('next-step').addEventListener('click', handleNext);
element('stop-refuel').addEventListener('click', handleRefuel);
element('reset-demo').addEventListener('click', resetDemo);
