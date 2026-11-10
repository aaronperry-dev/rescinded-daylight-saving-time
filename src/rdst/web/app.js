/* Swipe map: current DST vs rescinded vs permanent DST across CONUS.
 * Data comes from data/data.js (window.RDST); sunrise/sunset datasets are lazy-loaded
 * as data/solar/<key>.js, each calling RDST_LOAD(key, payload). Plain <script> loading
 * keeps the site working from file:// as well as over http(s). */
(function () {
  'use strict';

  const D = window.RDST;
  const SOLAR = D.solar;               // null when the site was built without sunrise/sunset
  const MINUS = '−';
  const $ = (id) => document.getElementById(id);
  const SIDES = ['left', 'right'];

  // ---------------------------------------------------------------- formatting
  const fmtSigned = (h) => (h < 0 ? MINUS : '+') + Math.abs(h);
  const fmtUtc = (h) => 'UTC' + fmtSigned(h);
  function fmtClock(min) {
    const m = ((Math.round(min) % 1440) + 1440) % 1440;
    const h = Math.floor(m / 60);
    return (h % 12 || 12) + ':' + String(m % 60).padStart(2, '0') + ' ' + (h < 12 ? 'AM' : 'PM');
  }
  function fmtDelta(min) {
    const r = Math.round(min);
    if (r === 0) return '—';
    const sign = r < 0 ? MINUS : '+';
    const a = Math.abs(r);
    return sign + (a % 60 === 0 ? a / 60 + ' h' : a + ' min');
  }
  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US',
      { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
  }

  // ----------------------------------------------------------- scenario maths
  const dstActive = (p, iso) => p.observes_dst && iso >= p.dst_start && iso <= p.dst_end;
  function offsetFor(p, iso, scen) {
    if (scen === 'rescinded') return p.std_offset;
    if (scen === 'permanent_dst') return p.dst_offset;
    return dstActive(p, iso) ? p.dst_offset : p.std_offset;
  }
  function abbrFor(p, iso, scen) {
    return p.observes_dst && offsetFor(p, iso, scen) === p.dst_offset ? p.dst_abbr : p.std_abbr;
  }
  const colorFor = (h) => D.offsetRamp[String(h)] || D.fallbackColor;

  // --------------------------------------------------------------------- state
  const defaultIdx = Math.max(0, D.dates.indexOf(D.year + '-07-01'));
  const state = { left: 'current', right: 'rescinded', mode: 'zones', stat: 'latest', dateIdx: defaultIdx, ratio: 0.5 };
  (function readHash() {
    const q = new URLSearchParams(location.hash.slice(1));
    const ok = (k, allowed) => allowed.includes(q.get(k));
    if (ok('l', Object.keys(D.scenarios))) state.left = q.get('l');
    if (ok('r', Object.keys(D.scenarios))) state.right = q.get('r');
    if (ok('m', ['zones', 'sunrise', 'sunset']) && (q.get('m') === 'zones' || SOLAR)) state.mode = q.get('m');
    if (ok('s', ['latest', 'earliest'])) state.stat = q.get('s');
    const d = parseInt(q.get('d'), 10);
    if (d >= 0 && d < D.dates.length) state.dateIdx = d;
  })();
  const isoDate = () => D.dates[state.dateIdx];
  const viewKey = () => state.mode + '_' + state.stat;

  // ----------------------------------------------------------------------- map
  const map = L.map('map', {
    zoomControl: false, minZoom: 3, maxZoom: 12, zoomSnap: 0.5, zoomDelta: 0.5, wheelPxPerZoomLevel: 90,
  });
  const CONUS_BOUNDS = [[24.5, -125], [49.6, -66.6]];
  map.fitBounds(CONUS_BOUNDS, { padding: [8, 8] });
  L.control.zoom({ position: 'topleft' }).addTo(map);

  map.createPane('left').style.zIndex = 450;
  map.createPane('right').style.zIndex = 450;
  map.createPane('borders').style.zIndex = 500;
  map.getPane('borders').style.pointerEvents = 'none';
  map.createPane('labels').style.zIndex = 650;
  map.getPane('labels').style.pointerEvents = 'none';

  const carto = (style, opts) => L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/' + style + '/{z}/{x}/{y}{r}.png',
    Object.assign({ subdomains: 'abcd', maxZoom: 20,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>' }, opts));
  const esri = (svc, opts) => L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/' + svc + '/MapServer/tile/{z}/{y}/{x}',
    Object.assign({ maxZoom: 19, attribution: 'Tiles &copy; Esri' }, opts));
  const basemaps = {
    'Light': L.layerGroup([carto('light_nolabels'), carto('light_only_labels', { pane: 'labels' })]),
    'Dark': L.layerGroup([carto('dark_nolabels'), carto('dark_only_labels', { pane: 'labels' })]),
    'Streets': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }),
    'Satellite': L.layerGroup([esri('World_Imagery'), esri('Reference/World_Boundaries_and_Places', { pane: 'labels' })]),
  };
  basemaps['Light'].addTo(map);
  L.control.layers(basemaps, null, { position: 'topright' }).addTo(map);

  // thin state lines, then a dark halo + white line for zone borders (shared by both sides)
  L.geoJSON(D.states, { pane: 'borders', interactive: false,
    style: { fill: false, color: '#5d5c58', weight: 0.8, opacity: 0.85 } }).addTo(map);
  L.geoJSON(D.zones, { pane: 'borders', interactive: false,
    style: { fill: false, color: '#0b0b0b', weight: 4, opacity: 0.22 } }).addTo(map);
  L.geoJSON(D.zones, { pane: 'borders', interactive: false,
    style: { fill: false, color: '#ffffff', weight: 2, opacity: 0.95 } }).addTo(map);

  const groupLabels = L.layerGroup(D.groupLabels.map((g) => L.marker([g.lat, g.lon], {
    pane: 'labels', interactive: false, keyboard: false,
    icon: L.divIcon({ className: 'zone-label', html: '<span>' + g.text + '</span>', iconSize: [0, 0] }),
  }))).addTo(map);
  const syncZoomClass = () => map.getContainer().classList.toggle('map-narrow', map.getZoom() > 6.5);
  map.on('zoomend', syncZoomClass); syncZoomClass();

  // ------------------------------------------------------- per-side data layers
  const layers = {};
  SIDES.forEach((side) => {
    layers[side] = {
      zones: L.geoJSON(D.zones, {
        pane: side,
        style: (f) => zoneStyle(side, f),
        onEachFeature: (f, lyr) => {
          lyr.bindTooltip(() => zoneTip(side, f.properties), { sticky: true });
          lyr.on('mouseover', () => showHover(f.properties));
          lyr.on('mouseout', () => showHover(null));
        },
      }),
      bands: L.featureGroup(),
      lines: L.featureGroup(),
      labels: L.layerGroup(),
    };
  });

  function zoneStyle(side, f) {
    const c = colorFor(offsetFor(f.properties, isoDate(), state[side]));
    return { fillColor: c, fillOpacity: 0.82, color: c, weight: 1, opacity: 0.82 };
  }
  function zoneTip(side, p) {
    const iso = isoDate(), s = state[side];
    return '<b>' + p.tzid + '</b><br>' + D.scenarioShort[s] + ': ' + fmtUtc(offsetFor(p, iso, s)) + ' (' + abbrFor(p, iso, s) + ')';
  }
  function showHover(p) {
    const el = $('hoverCard');
    if (!p || state.mode !== 'zones') { el.innerHTML = state.mode === 'zones' ? 'Hover a zone for details.' : ''; return; }
    const iso = isoDate();
    const part = (side) => {
      const s = state[side];
      return D.scenarioShort[s] + ' ' + fmtUtc(offsetFor(p, iso, s)) + ' (' + abbrFor(p, iso, s) + ')';
    };
    const dl = offsetFor(p, iso, state.right) - offsetFor(p, iso, state.left);
    el.innerHTML = '<b>' + p.tzid + '</b> &middot; ' + (p.observes_dst ? 'observes DST' : 'no DST') + '<br>' +
      part('left') + ' &rarr; ' + part('right') + (dl ? ' (' + fmtDelta(dl * 60) + ')' : '');
  }

  // --------------------------------------------------------- swipe divider
  const mapEl = map.getContainer();
  const divider = document.createElement('div');
  divider.id = 'divider';
  divider.innerHTML = '<div class="chip left" id="chipLeft"></div><div class="chip right" id="chipRight"></div>' +
    '<div class="line"></div>' +
    '<div class="handle" id="handle" role="slider" tabindex="0" aria-label="Comparison divider" aria-valuemin="0" aria-valuemax="100">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 7l-5 5 5 5M16 7l5 5-5 5"/></svg></div>';
  mapEl.appendChild(divider);
  L.DomEvent.disableClickPropagation(divider);
  L.DomEvent.disableScrollPropagation(divider);

  function updateClip() {
    const size = map.getSize();
    const x = Math.round(size.x * state.ratio);
    const nw = map.containerPointToLayerPoint([0, 0]);
    const se = map.containerPointToLayerPoint(size);
    const cx = nw.x + x;
    map.getPane('left').style.clip = 'rect(' + nw.y + 'px,' + cx + 'px,' + se.y + 'px,' + nw.x + 'px)';
    map.getPane('right').style.clip = 'rect(' + nw.y + 'px,' + se.x + 'px,' + se.y + 'px,' + cx + 'px)';
    divider.style.left = x + 'px';
    $('handle').setAttribute('aria-valuenow', Math.round(state.ratio * 100));
  }
  function setRatio(r) { state.ratio = Math.min(0.98, Math.max(0.02, r)); updateClip(); }
  map.on('move zoom viewreset resize', updateClip);

  let dragging = false;
  divider.addEventListener('pointerdown', (e) => {
    if (!e.target.closest('.line, .handle')) return;
    dragging = true; divider.setPointerCapture(e.pointerId); e.preventDefault();
  });
  divider.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const r = mapEl.getBoundingClientRect();
    setRatio((e.clientX - r.left) / r.width);
  });
  const endDrag = (e) => { dragging = false; try { divider.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ } };
  divider.addEventListener('pointerup', endDrag);
  divider.addEventListener('pointercancel', endDrag);
  $('handle').addEventListener('keydown', (e) => {
    const step = e.shiftKey ? 0.1 : 0.02;
    if (e.key === 'ArrowLeft') { setRatio(state.ratio - step); e.preventDefault(); }
    if (e.key === 'ArrowRight') { setRatio(state.ratio + step); e.preventDefault(); }
    if (e.key === 'Home') { setRatio(0.02); e.preventDefault(); }
    if (e.key === 'End') { setRatio(0.98); e.preventDefault(); }
  });

  // ------------------------------------------------------- dataset loading
  const cache = {}, waiting = {};
  window.RDST_LOAD = function (key, payload) {
    cache[key] = payload;
    (waiting[key] || []).forEach((w) => w.res(payload));
    delete waiting[key];
  };
  function loadDataset(key) {
    return new Promise((res, rej) => {
      if (cache[key]) return res(cache[key]);
      const first = !waiting[key];
      (waiting[key] = waiting[key] || []).push({ res, rej });
      if (!first) return;
      const s = document.createElement('script');
      s.src = 'data/solar/' + key + '.js';
      s.onerror = () => { (waiting[key] || []).forEach((w) => w.rej(new Error('Missing ' + key))); delete waiting[key]; };
      document.head.appendChild(s);
    });
  }

  let renderToken = 0;
  function populateSolar(side, ds) {
    const view = SOLAR.views[ds.metric + '_' + ds.stat];
    const bins = view.legend.bins;
    const L_ = layers[side];
    L_.bands.clearLayers(); L_.lines.clearLayers(); L_.labels.clearLayers();
    L_.bands.addLayer(L.geoJSON(ds.bands, {
      pane: side,
      style: (f) => { const c = bins[f.properties.bin].color; return { fillColor: c, fillOpacity: 0.88, color: c, weight: 1, opacity: 0.88 }; },
      onEachFeature: (f, lyr) => {
        const k = f.properties.bin;
        const hi = k + 1 < bins.length ? bins[k + 1].from : view.legend.end;
        lyr.bindTooltip(view.title + '<br><b>' + bins[k].from + ' – ' + hi + '</b> (' + D.scenarioShort[ds.scenario] + ')', { sticky: true });
      },
    }));
    L_.lines.addLayer(L.geoJSON(ds.lines, { pane: side, interactive: false,
      style: { color: '#0b0b0b', weight: 1.1, opacity: 0.85 } }));
    ds.labels.forEach((l) => L_.labels.addLayer(L.marker([l[0], l[1]], {
      pane: side, interactive: false, keyboard: false,
      icon: L.divIcon({ className: 'iso-label', iconSize: [0, 0],
        html: '<span style="transform:rotate(' + l[3] + 'deg)">' + l[2] + '</span>' }),
    })));
  }

  // ------------------------------------------------------------------- render
  function setVisible(group, show) {
    SIDES.forEach((s) => {
      const lyr = layers[s][group];
      if (show && !map.hasLayer(lyr)) lyr.addTo(map);
      if (!show && map.hasLayer(lyr)) map.removeLayer(lyr);
    });
  }

  function render() {
    const zonesMode = state.mode === 'zones';
    $('viewBlock').hidden = zonesMode;
    $('dateBlock').hidden = !zonesMode;
    document.querySelectorAll('#modeSeg button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.mode === state.mode)));
    document.querySelectorAll('#statSeg button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.stat === state.stat)));
    $('selLeft').value = state.left; $('selRight').value = state.right;
    $('chipLeft').textContent = D.scenarios[state.left];
    $('chipRight').textContent = D.scenarios[state.right];
    history.replaceState(null, '', '#' + new URLSearchParams({
      l: state.left, r: state.right, m: state.mode, s: state.stat, d: String(state.dateIdx) }).toString());

    setVisible('zones', zonesMode);
    setVisible('bands', !zonesMode); setVisible('lines', !zonesMode); setVisible('labels', !zonesMode);

    if (zonesMode) {
      SIDES.forEach((s) => layers[s].zones.setStyle((f) => zoneStyle(s, f)));
      renderZoneLegend(); renderZoneTable(); renderZoneStatus(); showHover(null);
    } else {
      renderSolar();
    }
  }

  function renderSolar() {
    const token = ++renderToken;
    const view = SOLAR.views[viewKey()];
    $('status').textContent = 'Loading…';
    $('hoverCard').innerHTML = '';
    renderSolarLegend(view);
    Promise.all(SIDES.map((s) => loadDataset(viewKey() + '_' + state[s]))).then((ds) => {
      if (token !== renderToken) return;           // a newer selection superseded this one
      SIDES.forEach((s, i) => populateSolar(s, ds[i]));
      renderCityTable(ds[0], ds[1], view);
      const what = state.mode === 'sunrise' ? 'sunrise' : 'sunset';
      $('status').textContent = 'Each place shows the ' + state.stat + ' ' + what + ' it sees on any day of ' + D.year +
        ', in local clock time. Isochrones are labelled every 30 minutes and jump at zone borders.';
    }).catch(() => {
      if (token !== renderToken) return;
      $('status').textContent = 'Sunrise/sunset data is missing. Run `rdst solar` and rebuild the site.';
    });
  }

  // ----------------------------------------------------------- sidebar widgets
  function renderZoneLegend() {
    const iso = isoDate();
    const present = new Set();
    D.zones.features.forEach((f) => SIDES.forEach((s) => present.add(offsetFor(f.properties, iso, state[s]))));
    const offs = [...present].sort((a, b) => b - a);
    $('legendTitle').textContent = 'Clock offset from UTC';
    $('legend').innerHTML = '<div class="legend-offsets">' +
      offs.map((h) => '<span><i style="background:' + colorFor(h) + '"></i>' + fmtUtc(h) + '</span>').join('') + '</div>' +
      '<p class="legend-note">Same colour = same clock time on both sides.</p>';
  }

  function renderSolarLegend(view) {
    $('legendTitle').textContent = view.title;
    const bins = view.legend.bins;
    $('legend').innerHTML = '<div class="ramp">' + bins.map((b) => '<i style="background:' + b.color + '"></i>').join('') + '</div>' +
      '<div class="ramp-labels">' + bins.map((b, i) => '<span>' + (i % 2 === 0 && i !== bins.length - 1 ? b.from : '') + '</span>').join('') +
      '<span>' + view.legend.end + '</span></div>' +
      '<p class="legend-note">30-minute bands; first and last bands are open-ended. Same scale on both sides.</p>';
  }

  function renderZoneStatus() {
    const iso = isoDate();
    const n = D.zones.features.filter((f) => dstActive(f.properties, iso)).length;
    $('dateLabel').textContent = fmtDate(iso);
    $('status').textContent = n
      ? 'DST is in effect in ' + n + ' of ' + D.zones.features.length + ' zones under current law on this date.'
      : 'No zone is on DST on this date, so current law and rescinded DST look identical.';
  }

  function renderZoneTable() {
    const iso = isoDate();
    const seen = new Map();
    D.zones.features.forEach((f) => { if (!seen.has(f.properties.group)) seen.set(f.properties.group, f.properties); });
    const rows = [...seen.values()].sort((a, b) => (b.std_offset - a.std_offset) || (b.observes_dst - a.observes_dst));
    $('tableTitle').textContent = 'Clock offset on ' + fmtDate(iso);
    $('tableHead').innerHTML = '<tr><th>Zone</th><th class="left">' + D.scenarioShort[state.left] + '</th><th class="right">' +
      D.scenarioShort[state.right] + '</th><th class="delta">Shift</th></tr>';
    $('tableBody').innerHTML = rows.map((p) => {
      const a = offsetFor(p, iso, state.left), b = offsetFor(p, iso, state.right);
      return '<tr><td>' + p.group + '</td><td>' + fmtUtc(a) + ' ' + abbrFor(p, iso, state.left) + '</td><td>' +
        fmtUtc(b) + ' ' + abbrFor(p, iso, state.right) + '</td><td class="delta">' + fmtDelta((b - a) * 60) + '</td></tr>';
    }).join('');
  }

  function renderCityTable(dl, dr, view) {
    $('tableTitle').textContent = 'Cities · ' + view.title.toLowerCase();
    $('tableHead').innerHTML = '<tr><th>City</th><th class="left">' + D.scenarioShort[state.left] + '</th><th class="right">' +
      D.scenarioShort[state.right] + '</th><th class="delta">Shift</th></tr>';
    $('tableBody').innerHTML = SOLAR.cities.map((c) => {
      const a = dl.cities[c], b = dr.cities[c];
      return '<tr><td>' + c + '</td><td>' + fmtClock(a) + '</td><td>' + fmtClock(b) + '</td><td class="delta">' + fmtDelta(b - a) + '</td></tr>';
    }).join('');
  }

  // ------------------------------------------------------------------ wiring
  (function buildControls() {
    $('yearTag').textContent = '· ' + D.year + ' rules';
    $('yearNote').textContent = D.year;
    $('tzRelease').textContent = D.tzRelease;
    $('built').textContent = D.generatedUtc;
    const opts = Object.entries(D.scenarios).map(([k, v]) => '<option value="' + k + '">' + v + '</option>').join('');
    $('selLeft').innerHTML = opts; $('selRight').innerHTML = opts;
    $('selLeft').addEventListener('change', (e) => { state.left = e.target.value; render(); });
    $('selRight').addEventListener('change', (e) => { state.right = e.target.value; render(); });

    if (!SOLAR) document.querySelectorAll('#modeSeg [data-mode="sunrise"], #modeSeg [data-mode="sunset"]').forEach((b) => { b.hidden = true; });
    document.querySelectorAll('#modeSeg button').forEach((b) => b.addEventListener('click', () => { state.mode = b.dataset.mode; render(); }));
    document.querySelectorAll('#statSeg button').forEach((b) => b.addEventListener('click', () => { state.stat = b.dataset.stat; render(); }));

    const range = $('dateRange');
    range.max = String(D.dates.length - 1); range.value = String(state.dateIdx);
    range.addEventListener('input', () => { state.dateIdx = parseInt(range.value, 10); render(); });
    $('dstStrip').innerHTML = D.dates.map((iso) => {
      const on = D.zones.features.some((f) => dstActive(f.properties, iso));
      return '<i class="' + (on ? 'dst' : '') + '" title="' + fmtDate(iso) + '"></i>';
    }).join('');
  })();

  map.whenReady(() => { updateClip(); render(); });
})();
