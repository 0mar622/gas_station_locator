const form = document.getElementById('trip-form');
const statusBox = document.getElementById('status');
const stationsList = document.getElementById('stations-list');
const routeMap = document.getElementById('route-map');

const field = (name) => form.elements[name];

const escapeHtml = (value) => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');

const setStatus = (message, type = '') => {
  statusBox.textContent = message;
  statusBox.className = `status ${type}`.trim();
};

const syncFuelGallonsFromPercent = () => {
  const percent = Number(field('current_fuel_percent').value);
  const capacity = Number(field('fuel_capacity_gallons').value);
  if (!Number.isFinite(percent) || !Number.isFinite(capacity) || capacity <= 0) return;

  field('current_fuel_gallons').value = ((percent / 100) * capacity).toFixed(1);
};

const syncFuelPercentFromGallons = () => {
  const gallons = Number(field('current_fuel_gallons').value);
  const capacity = Number(field('fuel_capacity_gallons').value);
  if (!Number.isFinite(gallons) || !Number.isFinite(capacity) || capacity <= 0) return;

  const percent = Math.min(100, Math.max(0, (gallons / capacity) * 100));
  field('current_fuel_percent').value = percent.toFixed(1);
};

const renderStations = (stations) => {
  if (!Array.isArray(stations) || stations.length === 0) {
    stationsList.innerHTML = '<div class="station-card"><h3>No gas stations found</h3><div class="station-meta"><span>Try widening the route radius or changing the fuel type.</span></div></div>';
    return;
  }

  stationsList.innerHTML = stations.map((station) => {
    const name = escapeHtml(station.name || 'Unnamed station');
    const price = station.price != null ? `$${Number(station.price).toFixed(2)}` : 'Price unavailable';
    const distance = station.distance_to_route_miles != null
      ? `${Number(station.distance_to_route_miles).toFixed(1)} mi off route`
      : 'Distance unavailable';
    const fuelType = station.fuel_type ? escapeHtml(station.fuel_type.toUpperCase()) : 'Fuel';
    const routeProgress = station.route_progress_miles != null
      ? `Route: ${Number(station.route_progress_miles).toFixed(1)} mi`
      : 'Route info unavailable';

    return `
      <div class="station-card">
        <h3>${name}</h3>
        <div class="station-meta">
          <span>${fuelType}</span>
          <span>${distance}</span>
          <span>${routeProgress}</span>
        </div>
        <div class="station-price">${price}</div>
      </div>
    `;
  }).join('');
};

const renderMap = (route, stations, origin, destination) => {
  const feature = route?.features?.[0];
  const coordinates = feature?.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length === 0) {
    routeMap.srcdoc = '<!doctype html><html><body style="margin:0;background:#dbeafe;display:flex;align-items:center;justify-content:center;font-family:sans-serif;color:#334155">No route available.</body></html>';
    return;
  }

  const points = coordinates.map(([longitude, latitude]) => [latitude, longitude]);
  const stationMarkers = (stations || []).map((station, index) => {
    const latitude = Number(station.latitude);
    const longitude = Number(station.longitude);
    const name = escapeHtml(station.name || `Station ${index + 1}`).replace(/\\n/g, ' ');
    const price = station.price != null ? Number(station.price).toFixed(2) : 'N/A';
    const popup = JSON.stringify(`<b>${name}</b><br>$${price}/gal`);
    return `L.marker([${latitude}, ${longitude}]).addTo(map).bindTooltip(${JSON.stringify(name)}, {permanent: true, direction: 'top', className: 'station-label'}).bindPopup(${popup});`;
  }).join('\n');

  const endpointMarkers = [
    { point: origin, label: 'Start', className: 'endpoint-label start-label' },
    { point: destination, label: 'Destination', className: 'endpoint-label destination-label' },
  ].filter(({ point }) => Number.isFinite(Number(point?.latitude)) && Number.isFinite(Number(point?.longitude)))
    .map(({ point, label, className }) => {
      const latitude = Number(point.latitude);
      const longitude = Number(point.longitude);
      return `L.marker([${latitude}, ${longitude}]).addTo(map).bindTooltip(${JSON.stringify(label)}, {permanent: true, direction: 'top', className: '${className}'});`;
    }).join('\n');

  routeMap.srcdoc = `
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <style>
          html,body,#map{margin:0;height:100%;width:100%}
          body{background:#dbeafe}
          .leaflet-tooltip{border:0;box-shadow:0 2px 8px rgba(15,23,42,.25);font:600 12px system-ui,sans-serif}
          .station-label{background:#ffffff;color:#0f766e}
          .endpoint-label{color:#ffffff;font-weight:700}
          .start-label{background:#15803d}
          .destination-label{background:#b91c1c}
        </style>
      </head>
      <body>
        <div id="map"></div>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script>
          const map = L.map('map').setView([${points[0][0]}, ${points[0][1]}], 10);
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);
          const routePoints = ${JSON.stringify(points)};
          L.polyline(routePoints, { color: '#2563eb', weight: 5, opacity: 0.8 }).addTo(map);
          ${endpointMarkers}
          ${stationMarkers}
          map.fitBounds(routePoints, { padding: [20, 20] });
        </script>
      </body>
    </html>
  `;
};

field('current_fuel_percent').addEventListener('input', syncFuelGallonsFromPercent);
field('current_fuel_gallons').addEventListener('input', syncFuelPercentFromGallons);
field('fuel_capacity_gallons').addEventListener('input', () => {
  if (field('current_fuel_percent').value) syncFuelGallonsFromPercent();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = {
    starting_location: field('starting_location').value.trim(),
    destination: field('destination').value.trim(),
    fuel_type: field('fuel_type').value,
    current_fuel_gallons: Number(field('current_fuel_gallons').value),
    vehicle_mpg: Number(field('vehicle_mpg').value),
  };
  const paymentMethod = field('payment_method').value;

  try {
    setStatus('Sending trip details...');
    const response = await fetch(form.action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Trip request failed.');

    document.getElementById('range-value').textContent = `${result.estimated_range_miles ?? '-'} mi`;
    document.getElementById('distance-value').textContent = `${result.distance_miles ?? '-'} mi`;
    document.getElementById('duration-value').textContent = `${result.duration_minutes ?? '-'} min`;
    document.getElementById('payment-value').textContent = paymentMethod === 'cash' ? 'Cash' : 'Card';
    renderStations(result.stations);
    renderMap(result.route, result.stations, result.origin, result.destination);
    setStatus('Trip planned successfully.', 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  }
});
