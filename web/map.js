/* The world map on the dashboard.

   Three things are drawn on one equirectangular map: the coastlines from
   world.js, every customer at their real position, and the day/night
   terminator — the wave that shows, at a glance, who is at their desk and
   who is asleep. The sun and moon sit at the point on earth each is directly
   overhead.

   The sun and moon positions are worked out here rather than fetched. Both
   use the low-precision formulae from Astronomical Algorithms, good to a
   fraction of a degree, which is far better than a map two pixels to the
   degree can show. */

const MAP_W = 720;             /* 2 px per degree of longitude */
const MAP_H = 360;

const rad = d => d * Math.PI / 180;
const deg = r => r * 180 / Math.PI;
const wrap180 = d => ((((d + 180) % 360) + 360) % 360) - 180;

const px = lon => (wrap180(lon) + 180) * (MAP_W / 360);
const py = lat => (90 - lat) * (MAP_H / 180);

/* --------------------------------------------------------------- the sky */

function julianDay(date) {
  return date.getTime() / 86400000 + 2440587.5;
}

/* Greenwich mean sidereal time, in degrees. */
function gmst(days) {
  return (280.46061837 + 360.98564736629 * days) % 360;
}

function sunPosition(date) {
  const n = julianDay(date) - 2451545.0;
  const meanLon = rad((280.460 + 0.9856474 * n) % 360);
  const anomaly = rad((357.528 + 0.9856003 * n) % 360);
  const ecliptic = meanLon + rad(1.915) * Math.sin(anomaly)
                           + rad(0.020) * Math.sin(2 * anomaly);
  const tilt = rad(23.439 - 0.0000004 * n);

  const ra = Math.atan2(Math.cos(tilt) * Math.sin(ecliptic), Math.cos(ecliptic));
  const dec = Math.asin(Math.sin(tilt) * Math.sin(ecliptic));
  return {
    lat: deg(dec),
    lon: wrap180(deg(ra) - gmst(n)),
    lambda: deg(ecliptic),
  };
}

function moonPosition(date) {
  const n = julianDay(date) - 2451545.0;
  const t = n / 36525;

  const meanLon = (218.316 + 481267.8813 * t) % 360;
  const anomaly = rad((134.963 + 477198.8676 * t) % 360);
  const latArg = rad((93.272 + 483202.0175 * t) % 360);

  /* The two largest terms only: evection and the principal latitude term. */
  const ecliptic = rad(meanLon + 6.289 * Math.sin(anomaly) / 1);
  const beta = rad(5.128 * Math.sin(latArg));
  const tilt = rad(23.439 - 0.0000004 * n);

  const ra = Math.atan2(
    Math.sin(ecliptic) * Math.cos(tilt) - Math.tan(beta) * Math.sin(tilt),
    Math.cos(ecliptic));
  const dec = Math.asin(Math.sin(beta) * Math.cos(tilt)
                        + Math.cos(beta) * Math.sin(tilt) * Math.sin(ecliptic));
  return {
    lat: deg(dec),
    lon: wrap180(deg(ra) - gmst(n)),
    lambda: deg(ecliptic),
  };
}

/* How much of the moon's disc is lit, 0 (new) to 1 (full). */
function moonPhase(sun, moon) {
  const elongation = rad(wrap180(moon.lambda - sun.lambda));
  return (1 - Math.cos(elongation)) / 2;
}

/* --------------------------------------------------------------- drawing */

function pathFor(points, close) {
  let out = '';
  points.forEach(([lon, lat], i) => {
    out += (i ? 'L' : 'M') + px(lon).toFixed(1) + ' ' + py(lat).toFixed(1) + ' ';
  });
  return out + (close ? 'Z' : '');
}

/* The edge of daylight, sampled one longitude at a time.

   For a given meridian the sun sits on the horizon at a single latitude,
   which is all the fill needs to know: everything on the dark side of that
   latitude is in night. */
function terminator(sun) {
  const declination = Math.abs(sun.lat) < 0.01 ? (sun.lat < 0 ? -0.01 : 0.01)
                                               : sun.lat;
  const points = [];
  for (let lon = -180; lon <= 180; lon += 1.5) {
    const hourAngle = rad(lon - sun.lon);
    const lat = deg(Math.atan(-Math.cos(hourAngle) / Math.tan(rad(declination))));
    points.push([lon, Math.max(-89.9, Math.min(89.9, lat))]);
  }
  return points;
}

/* The same edge drawn as a line, which needs more care than the fill does.

   The terminator is a great circle a quarter turn from the point the sun is
   overhead, so it is traced by walking every bearing out from that point.
   Sampling by longitude instead would fail twice a year: at an equinox the
   line runs pole to pole and a longitude has no single answer. The curve is
   cut wherever it leaves one side of the map and comes back the other. */
function terminatorCurve(sun) {
  const lat0 = rad(sun.lat);
  const segments = [];
  let current = [];
  let previous = null;

  for (let bearing = 0; bearing <= 360; bearing += 2) {
    const theta = rad(bearing);
    const lat = Math.asin(Math.cos(lat0) * Math.cos(theta));
    const lon = sun.lon + deg(Math.atan2(
      Math.sin(theta) * Math.cos(lat0),
      -Math.sin(lat0) * Math.sin(lat)));
    /* Longitude means nothing at the pole itself, where every meridian
       meets: including that point would drag the line across the map. */
    if (Math.abs(deg(lat)) > 89.5) {
      if (current.length > 1) segments.push(current);
      current = [];
      previous = null;
      continue;
    }
    const point = [wrap180(lon), deg(lat)];

    if (previous && Math.abs(point[0] - previous[0]) > 180) {
      if (current.length > 1) segments.push(current);
      current = [];
    }
    current.push(point);
    previous = point;
  }
  if (current.length > 1) segments.push(current);
  return segments;
}

/* The dark half of the world: the terminator, closed off at whichever pole
   is in shadow. With the sun north of the equator the south is dark. */
function nightShape(sun) {
  const line = terminator(sun);
  const edge = sun.lat > 0 ? -90 : 90;
  return [...line, [180, edge], [-180, edge]];
}

function landPaths() {
  return WORLD.map(shape =>
    `<path class="land" d="${pathFor(shape, true)}"/>`).join('');
}

function graticule() {
  let out = '';
  for (let lon = -150; lon <= 150; lon += 30) {
    out += `<line class="grat" x1="${px(lon)}" y1="0" x2="${px(lon)}" y2="${MAP_H}"/>`;
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    out += `<line class="grat" x1="0" y1="${py(lat)}" x2="${MAP_W}" y2="${py(lat)}"/>`;
  }
  out += `<line class="equator" x1="0" y1="${py(0)}" x2="${MAP_W}" y2="${py(0)}"/>`;
  return out;
}

function moonGlyph(moon, lit) {
  const x = px(moon.lon);
  const y = py(moon.lat);
  /* A disc with a bite taken out of it, the bite shrinking towards full. */
  const offset = (1 - lit) * 11;
  return `
    <g class="moon" transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">
      <circle class="moonhalo" r="13"/>
      <defs>
        <mask id="moonmask">
          <circle r="6" fill="#fff"/>
          <circle r="6" cx="${offset.toFixed(2)}" fill="#000"/>
        </mask>
      </defs>
      <circle class="moondisc" r="6" mask="url(#moonmask)"/>
      <circle class="moonring" r="6"/>
    </g>`;
}

function sunGlyph(sun) {
  const x = px(sun.lon);
  const y = py(sun.lat);
  let rays = '';
  for (let i = 0; i < 8; i++) {
    const a = rad(i * 45);
    rays += `<line class="ray" x1="${(Math.cos(a) * 9).toFixed(1)}"
                   y1="${(Math.sin(a) * 9).toFixed(1)}"
                   x2="${(Math.cos(a) * 14).toFixed(1)}"
                   y2="${(Math.sin(a) * 14).toFixed(1)}"/>`;
  }
  return `
    <g class="sun" transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">
      <circle class="sunhalo" r="20"/>
      ${rays}
      <circle class="sundisc" r="7"/>
    </g>`;
}

function pins(points) {
  return points.map(point => {
    const x = px(point.lon);
    const y = py(point.lat);
    const size = 3 + Math.min(5, Math.sqrt(point.open || 0) * 1.6);
    const kind = point.alerts ? 'alert' : (point.open ? 'busy' : 'idle');
    return `
      <g class="pin ${kind}" data-company="${point.id}"
         transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">
        <circle class="halo" r="${(size + 7).toFixed(1)}"/>
        <circle class="dot" r="${size.toFixed(1)}"/>
        <title>${point.name} — ${point.city || point.country_name}
${point.open} open · ${point.alerts} flagged</title>
      </g>`;
  }).join('');
}

/* ----------------------------------------------------------- local times */

function timeIn(zone, date) {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: zone, hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(date);
  } catch (err) {
    return '--:--';
  }
}

function dayIn(zone, date) {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: zone, weekday: 'short',
    }).format(date).toUpperCase();
  } catch (err) {
    return '';
  }
}

/* Whole hours between a zone and this computer, for the "+8h" label. */
function offsetHours(zone, date) {
  try {
    const there = new Date(date.toLocaleString('en-US', { timeZone: zone }));
    const here = new Date(date.toLocaleString('en-US'));
    return Math.round((there - here) / 3600000);
  } catch (err) {
    return 0;
  }
}

/* Office hours, roughly: who could pick up the phone right now. */
function awake(zone, date) {
  const hour = Number(timeIn(zone, date).slice(0, 2));
  if (Number.isNaN(hour)) return 'night';
  if (hour >= 9 && hour < 18) return 'open';
  if (hour >= 7 && hour < 22) return 'edge';
  return 'night';
}

function clockStrip(points, date) {
  const zones = new Map();
  points.forEach(point => {
    const key = point.timezone || 'UTC';
    if (!zones.has(key)) {
      zones.set(key, { zone: key, places: [], open: 0, alerts: 0 });
    }
    const entry = zones.get(key);
    entry.places.push(point.city || point.country_name || point.name);
    entry.open += point.open || 0;
    entry.alerts += point.alerts || 0;
  });

  const rows = [...zones.values()].sort(
    (a, b) => offsetHours(a.zone, date) - offsetHours(b.zone, date));

  return rows.map(row => {
    const offset = offsetHours(row.zone, date);
    const label = [...new Set(row.places)].slice(0, 3).join(' · ');
    return `
      <div class="wclock ${awake(row.zone, date)}" data-zone="${row.zone}">
        <div class="wtime">${timeIn(row.zone, date)}</div>
        <div class="wplace">${label}</div>
        <div class="wmeta">${dayIn(row.zone, date)}
          <span>${offset === 0 ? 'same time'
                  : (offset > 0 ? '+' : '') + offset + 'h'}</span>
          ${row.open ? `<span class="wopen">${row.open} open</span>` : ''}
          ${row.alerts ? `<span class="walert">${row.alerts}</span>` : ''}
        </div>
      </div>`;
  }).join('');
}

/* ------------------------------------------------------------- the view */

const MapView = {
  data: null,
  timer: null,

  html() {
    return `
      <div class="mapwrap">
        <div class="maphead">
          <span class="mtitle">CUSTOMER WORLD</span>
          <span class="mlegend">
            <i class="lg-day"></i>daylight <i class="lg-night"></i>night
            <i class="lg-pin"></i>customer <i class="lg-alert"></i>flagged
          </span>
          <span class="mutc" id="map-utc"></span>
        </div>
        <svg id="worldmap" viewBox="0 0 ${MAP_W} ${MAP_H}"
             preserveAspectRatio="xMidYMid meet" role="img"
             aria-label="World map of customer locations"></svg>
        <div class="clocks" id="worldclocks"></div>
        <div class="mapnote" id="mapnote"></div>
      </div>`;
  },

  mount(data) {
    this.data = data;
    this.draw();
    if (this.timer) clearInterval(this.timer);
    /* A minute is plenty: the terminator moves a quarter of a degree. */
    this.timer = setInterval(() => this.draw(), 30000);
  },

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  },

  draw() {
    const svg = document.getElementById('worldmap');
    if (!svg || !this.data) { this.stop(); return; }

    const now = new Date();
    const sun = sunPosition(now);
    const moon = moonPosition(now);
    const lit = moonPhase(sun, moon);
    const points = this.data.points || [];

    svg.innerHTML = `
      <rect class="ocean" x="0" y="0" width="${MAP_W}" height="${MAP_H}"/>
      ${graticule()}
      ${landPaths()}
      <path class="night" d="${pathFor(nightShape(sun), true)}"/>
      <path class="termline" d="${terminatorCurve(sun)
                  .map(segment => pathFor(segment, false)).join(' ')}"/>
      ${sunGlyph(sun)}
      ${moonGlyph(moon, lit)}
      ${pins(points)}`;

    const utc = document.getElementById('map-utc');
    if (utc) {
      utc.textContent = 'UTC ' + now.toISOString().slice(11, 16)
        + ' · moon ' + Math.round(lit * 100) + '% lit';
    }

    const clocks = document.getElementById('worldclocks');
    if (clocks) {
      clocks.innerHTML = points.length
        ? clockStrip(points, now)
        : '<div class="note">No customer has a country set yet. Open '
          + 'CUSTOMERS and give one a country to put it on the map.</div>';
    }

    const note = document.getElementById('mapnote');
    if (note) {
      const missing = (this.data.unplaced || []).length;
      note.textContent = missing
        ? `${missing} customer${missing === 1 ? '' : 's'} not on the map — `
          + 'set a country on the CUSTOMERS page.'
        : '';
    }
  },
};
