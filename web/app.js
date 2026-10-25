// PlanOps Tactical Floor Plan & Route Desk
const $ = s => document.querySelector(s);
const canvas = $('#planCanvas'), ctx = canvas.getContext('2d');

let data = null;
let sourceFile = null;
let mode = 'full';
let zoom = 1;
let offset = { x: 0, y: 0 };
let selected = null;
let hidden = new Set();
let drag = null;

// Route Planning State
let activeRoute = null;
let startCoord = null;
let destCoord = null;
let pickMode = null; // null | 'start' | 'dest'

const colors = {
  wall: '#455e52',
  door: '#087f9e',
  stair: '#7187a3',
  elevator: '#00897b',
  aed: '#e91e63',
  emergency_exit: '#d45242',
  entrance: '#ae8a3f',
  hydrant: '#dc6650',
  fire_extinguisher: '#dd7655',
  sprinkler: '#e39d56',
  fire_alarm: '#d96a51',
  fire_safety: '#ce7950',
  hazard: '#d84315',
  blocked: '#c62828',
  furniture: '#82958a',
  electrical: '#6d92a4',
  plumbing: '#5f9d9b',
  dimension: '#aaa79e',
  annotation: '#78907e',
  other: '#9ba49f',
};

function categoryDisplayName(cat) {
  if (cat === 'aed') return 'AED';
  if (cat === 'elevator') return 'Elevator';
  return cat.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function featPoints(f) {
  const g = f.geometry;
  if (!g) return [];
  if (g.type === 'Point') return [g.coordinates];
  if (g.type === 'LineString') return g.coordinates;
  if (g.type === 'Polygon') return g.coordinates.flat();
  return [];
}

function visible(f) {
  return !hidden.has(f.properties.category) && (mode === 'full' || f.properties.tactical);
}

function getBoundsAndScale(rect) {
  if (!data) return null;
  const all = data.features.flatMap(featPoints);
  if (!all.length) return null;
  const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const scale = Math.min((rect.width - 90) / (maxX - minX || 1), (rect.height - 90) / (maxY - minY || 1)) * zoom;
  const cx = rect.width / 2 + offset.x, cy = rect.height / 2 + offset.y;
  const midX = (minX + maxX) / 2, midY = (minY + maxY) / 2;
  return { scale, cx, cy, midX, midY };
}

function cadToScreen(p, bs) {
  return [bs.cx + (p[0] - bs.midX) * bs.scale, bs.cy - (p[1] - bs.midY) * bs.scale];
}

function screenToCad(px, py) {
  const rect = canvas.getBoundingClientRect();
  const bs = getBoundsAndScale(rect);
  if (!bs) return [0, 0];
  const x = bs.midX + (px - bs.cx) / bs.scale;
  const y = bs.midY - (py - bs.cy) / bs.scale;
  return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
}

function draw() {
  const rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  if (!data) return;
  const bs = getBoundsAndScale(rect);
  if (!bs) return;

  const screen = p => cadToScreen(p, bs);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // 1. Draw floor plan features
  for (const f of data.features) {
    if (!visible(f) || !f.geometry) continue;
    const p = f.properties, pts = featPoints(f).map(screen);
    const color = colors[p.category] || colors.other;
    const door = p.category === 'door';
    const isBlocked = p.category === 'blocked';
    const isHazard = p.category === 'hazard';
    const isElevator = p.category === 'elevator';
    const isAed = p.category === 'aed';
    const emphasis = mode === 'tactical' && (door || isBlocked || isHazard || isElevator || isAed);

    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.shadowColor = emphasis ? color : 'transparent';
    ctx.shadowBlur = emphasis ? 6 : 0;
    ctx.lineWidth = p.category === 'wall' ? 2.5 : isBlocked ? 3.5 : emphasis ? 3.0 : door ? 2.0 : 1.4;

    ctx.beginPath();
    if (f.geometry.type === 'Point' && p.cad_geometry === 'Arc') {
      const [x, y] = pts[0];
      const r = Math.max(emphasis ? 8 : 3, (p.radius || 0) * bs.scale);
      const start = -(p.start_angle || 0) * Math.PI / 180;
      const end = -(p.end_angle || 0) * Math.PI / 180;
      ctx.arc(x, y, r, start, end, true);
      ctx.stroke();
      if (door) {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + Math.cos(end) * r, y + Math.sin(end) * r);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x, y, emphasis ? 2.8 : 2.0, 0, Math.PI * 2);
        ctx.fill();
      }
    } else if (f.geometry.type === 'Point') {
      const [x, y] = pts[0];
      const r = p.radius ? Math.max(emphasis ? 8 : 4, p.radius * bs.scale) : (emphasis ? 6 : 4);
      if (isHazard) {
        // Draw hazard halo
        ctx.save();
        ctx.fillStyle = 'rgba(216, 67, 21, 0.22)';
        ctx.beginPath();
        ctx.arc(x, y, r * 1.4, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      } else if (isAed) {
        // Draw distinct AED medical beacon halo
        ctx.save();
        ctx.fillStyle = mode === 'tactical' ? 'rgba(233, 30, 99, 0.28)' : 'rgba(233, 30, 99, 0.16)';
        ctx.beginPath();
        ctx.arc(x, y, r * 1.6, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      } else if (isElevator) {
        // Draw distinct elevator car marker
        ctx.save();
        ctx.fillStyle = mode === 'tactical' ? 'rgba(0, 137, 123, 0.25)' : 'rgba(0, 137, 123, 0.15)';
        ctx.fillRect(x - r * 1.2, y - r * 1.2, r * 2.4, r * 2.4);
        ctx.strokeStyle = colors.elevator;
        ctx.lineWidth = emphasis ? 2.0 : 1.2;
        ctx.strokeRect(x - r * 1.2, y - r * 1.2, r * 2.4, r * 2.4);
        ctx.restore();
      }
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
      if (p.radius || isHazard || isAed) {
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.stroke();
      }
    } else {
      pts.forEach((q, i) => i ? ctx.lineTo(...q) : ctx.moveTo(...q));
      if (f.geometry.type === 'Polygon') {
        ctx.closePath();
        ctx.globalAlpha = isBlocked ? 0.35 : isElevator ? 0.22 : 0.08;
        ctx.fill();
        ctx.globalAlpha = 1;
      }
      ctx.stroke();
    }
    ctx.shadowBlur = 0;

    // Highlight selected feature
    if (selected === f) {
      ctx.save();
      ctx.strokeStyle = '#238d64';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      pts.forEach((q, i) => i ? ctx.lineTo(...q) : ctx.moveTo(...q));
      if (f.geometry.type === 'Point') {
        ctx.closePath();
        ctx.arc(...pts[0], 10, 0, Math.PI * 2);
      }
      ctx.stroke();
      ctx.restore();
    }
  }

  // 2. Draw Active Calculated Tactical Route
  if (activeRoute && activeRoute.path && activeRoute.path.length >= 2) {
    ctx.save();
    // Glowing cyan underlay
    ctx.strokeStyle = '#00e5ff';
    ctx.lineWidth = 5.5;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.shadowColor = '#00e5ff';
    ctx.shadowBlur = 10;
    ctx.beginPath();
    activeRoute.path.forEach((pt, i) => {
      const [sx, sy] = screen(pt);
      if (i === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    });
    ctx.stroke();

    // Inner bright core
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2.2;
    ctx.shadowBlur = 0;
    ctx.stroke();

    // Route waypoint dots
    for (const pt of activeRoute.path) {
      const [sx, sy] = screen(pt);
      ctx.fillStyle = '#00e5ff';
      ctx.beginPath();
      ctx.arc(sx, sy, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // Start Badge Marker
    const [startSx, startSy] = screen(activeRoute.path[0]);
    ctx.fillStyle = '#2e7d32';
    ctx.beginPath();
    ctx.arc(startSx, startSy, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(startSx, startSy, 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = 'bold 9px monospace';
    ctx.fillStyle = '#173f35';
    ctx.fillText('START', startSx + 11, startSy + 3);

    // Destination Badge Marker
    const [destSx, destSy] = screen(activeRoute.path[activeRoute.path.length - 1]);
    ctx.fillStyle = '#d32f2f';
    ctx.beginPath();
    ctx.arc(destSx, destSy, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(destSx, destSy, 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = 'bold 9px monospace';
    ctx.fillStyle = '#b71c1c';
    ctx.fillText(activeRoute.destination_info?.label || 'EXIT', destSx + 11, destSy + 3);

    ctx.restore();
  } else if (startCoord) {
    // Pending Start Pin
    const [sx, sy] = screen(startCoord);
    ctx.save();
    ctx.fillStyle = '#2e7d32';
    ctx.beginPath();
    ctx.arc(sx, sy, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = 'bold 9px monospace';
    ctx.fillStyle = '#173f35';
    ctx.fillText('START', sx + 10, sy + 3);
    ctx.restore();
  }
}

function fit() {
  offset = { x: 0, y: 0 };
  zoom = 1;
  $('#zoomLabel').textContent = '100%';
  draw();
}

function setMode(m) {
  mode = m;
  $('#fullMode').classList.toggle('active', m === 'full');
  $('#tacticalMode').classList.toggle('active', m === 'tactical');
  $('#tacticalBanner').classList.toggle('hidden', m !== 'tactical');
  draw();
}

function toast(t) {
  const el = $('#toast');
  el.textContent = t;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2400);
}

function switchTab(tab) {
  const isRoute = tab === 'route';
  $('#tabOverviewBtn').classList.toggle('active', !isRoute);
  $('#tabRouteBtn').classList.toggle('active', isRoute);
  $('#tabOverviewView').classList.toggle('active', !isRoute);
  $('#tabRouteView').classList.toggle('active', isRoute);
  $('#railDesk').classList.toggle('active', !isRoute);
  $('#railRoute').classList.toggle('active', isRoute);
}

function populateDestinations() {
  if (!data) return;
  const select = $('#destSelect');
  select.innerHTML = '<option value="nearest_exit">⭐ Nearest Reachable Exit (Auto-select)</option>';

  const exits = data.features.filter(f => f.properties.category === 'emergency_exit');
  const entrances = data.features.filter(f => f.properties.category === 'entrance');

  exits.forEach((f, i) => {
    const pts = featPoints(f);
    if (!pts.length) return;
    const pt = pts[0];
    const label = f.properties.display_name || `Exit ${i + 1}`;
    const handle = f.properties.source_handle || `EX${i + 1}`;
    select.innerHTML += `<option value="${pt[0]},${pt[1]}">Exit: ${label} [${handle}] · (${Math.round(pt[0])}, ${Math.round(pt[1])})</option>`;
  });

  entrances.forEach((f, i) => {
    const pts = featPoints(f);
    if (!pts.length) return;
    const pt = pts[0];
    const label = f.properties.display_name || `Entrance ${i + 1}`;
    select.innerHTML += `<option value="${pt[0]},${pt[1]}">Entrance: ${label} · (${Math.round(pt[0])}, ${Math.round(pt[1])})</option>`;
  });

  select.innerHTML += '<option value="custom">📍 Custom Coordinate (Pick on Canvas)</option>';
}

function renderCategories() {
  const counts = data.metadata.category_counts || {};
  $('#categories').innerHTML = Object.entries(counts)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([cat, n]) => `
      <label class="category-row">
        <input type="checkbox" data-cat="${cat}" ${hidden.has(cat) ? '' : 'checked'}>
        <i class="category-swatch" style="--swatch:${colors[cat] || colors.other}"></i>
        <span>${categoryDisplayName(cat)}</span>
        <small>${n}</small>
      </label>
    `).join('') || '<span class="empty-note">No model-space entities found.</span>';

  $('#categories').querySelectorAll('input').forEach(el => {
    el.onchange = () => {
      el.checked ? hidden.delete(el.dataset.cat) : hidden.add(el.dataset.cat);
      draw();
    };
  });
  $('#allToggle').textContent = hidden.size ? 'ALL ON' : 'ALL OFF';
}

function loadData(d, file = 'SAMPLE PLAN.DXF') {
  data = d;
  selected = null;
  hidden.clear();
  activeRoute = null;

  $('#fileName').textContent = file.toUpperCase();
  $('#fileMeta').textContent = `DXF · ${d.metadata.units_code ? 'UNIT CODE ' + d.metadata.units_code : 'LOCAL COORDINATES PRESERVED'}`;
  $('#emptyState').classList.add('hidden');
  $('#entityCount').textContent = d.metadata.entity_count;
  $('#fullCount').textContent = d.metadata.entity_count;

  const tactical = d.features.filter(f => f.properties.tactical).length;
  $('#tacticalCount').textContent = tactical;
  const supported = d.metadata.entity_count - d.metadata.unsupported_count;
  const pct = d.metadata.entity_count ? Math.round(supported / d.metadata.entity_count * 100) : 100;

  $('#supportPct').textContent = pct + '%';
  $('#supportBar').style.width = pct + '%';
  $('#supportSub').textContent = `${supported} supported · ${d.metadata.unsupported_count} unsupported`;
  $('#statusPill').className = 'status-pill ' + (d.metadata.unsupported_count ? 'warn' : 'ready');
  $('#statusPill').innerHTML = `<i></i> ${d.metadata.unsupported_count ? 'REVIEW' : 'READY'}`;
  $('#unitsLabel').textContent = `COORDINATES · LOCAL DXF · UNITS ${d.metadata.units_code}`;
  $('#coordLabel').textContent = `${d.metadata.entity_count} ENTITIES · ${Object.keys(d.metadata.category_counts || {}).length} CATEGORIES`;

  $('#geoBtn').disabled = $('#dxfBtn').disabled = $('#validateBtn').disabled = false;
  $('#planRouteBtn').disabled = false;

  // Set default start location
  startCoord = [3000, 2500];
  $('#startCoordDisplay').value = `${startCoord[0]}, ${startCoord[1]}`;

  populateDestinations();
  renderCategories();
  fit();
}

// File Upload Handler
$('#fileInput').onchange = async e => {
  const file = e.target.files[0];
  if (!file) return;
  $('#statusPill').className = 'status-pill';
  $('#statusPill').innerHTML = '<i></i> PARSING';
  try {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/convert', { method: 'POST', body: fd });
    if (!r.ok) {
      const err = await r.json();
      throw Error(err.detail || 'DXF could not be parsed');
    }
    sourceFile = file;
    loadData(await r.json(), file.name);
    toast('Plan parsed · tactical geometry active');
  } catch (err) {
    $('#statusPill').className = 'status-pill error';
    $('#statusPill').textContent = 'ERROR';
    toast(err.message);
  }
  e.target.value = '';
};

// Drag and drop for DXF
const dropTarget = $('#canvasWrap');
dropTarget.ondragover = e => { e.preventDefault(); dropTarget.style.outline = '2px dashed #65a17c'; };
dropTarget.ondragleave = () => { dropTarget.style.outline = ''; };
dropTarget.ondrop = e => {
  e.preventDefault();
  dropTarget.style.outline = '';
  const file = e.dataTransfer.files[0];
  if (file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    $('#fileInput').files = transfer.files;
    $('#fileInput').dispatchEvent(new Event('change'));
  }
};

// Tab switching
$('#tabOverviewBtn').onclick = () => switchTab('overview');
$('#tabRouteBtn').onclick = () => switchTab('route');
$('#railDesk').onclick = () => switchTab('overview');
$('#railRoute').onclick = () => switchTab('route');
$('#railReport').onclick = () => {
  switchTab('overview');
  $('.report-card').scrollIntoView({ behavior: 'smooth' });
};

// Modes & Zoom
$('#fullMode').onclick = () => setMode('full');
$('#tacticalMode').onclick = () => setMode('tactical');
$('#fitBtn').onclick = fit;
$('#zoomIn').onclick = () => {
  zoom = Math.min(zoom * 1.25, 10);
  $('#zoomLabel').textContent = Math.round(zoom * 100) + '%';
  draw();
};
$('#zoomOut').onclick = () => {
  zoom = Math.max(zoom / 1.25, 0.15);
  $('#zoomLabel').textContent = Math.round(zoom * 100) + '%';
  draw();
};
$('#allToggle').onclick = () => {
  if (hidden.size) hidden.clear();
  else Object.keys(data?.metadata.category_counts || {}).forEach(x => hidden.add(x));
  renderCategories();
  draw();
};

// Canvas Pointer Events (Pan, Zoom, Inspect, Pick)
canvas.onpointerdown = e => {
  drag = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y, moved: false };
  canvas.setPointerCapture(e.pointerId);
  canvas.classList.add('dragging');
};

canvas.onpointermove = e => {
  if (drag) {
    if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 3) drag.moved = true;
    offset = { x: drag.ox + e.clientX - drag.x, y: drag.oy + e.clientY - drag.y };
    draw();
    return;
  }
  if (!data) return;
  const cad = screenToCad(e.offsetX, e.offsetY);
  $('#coordLabel').textContent = `CAD (${cad[0]}, ${cad[1]}) · CANVAS ${e.offsetX}/${e.offsetY} PX`;
};

canvas.onpointerup = e => {
  canvas.classList.remove('dragging');
  if (!drag) return;

  if (!drag.moved) {
    const cad = screenToCad(e.offsetX, e.offsetY);

    if (pickMode === 'start') {
      startCoord = cad;
      $('#startCoordDisplay').value = `${startCoord[0]}, ${startCoord[1]}`;
      pickMode = null;
      $('#pickStartBtn').classList.remove('active');
      $('#pickIndicator').classList.add('hidden');
      canvas.classList.remove('crosshair');
      toast(`Start set to (${cad[0]}, ${cad[1]})`);
      draw();
      return;
    }

    if (pickMode === 'dest') {
      destCoord = cad;
      $('#destSelect').value = 'custom';
      pickMode = null;
      $('#pickDestBtn').classList.remove('active');
      $('#pickIndicator').classList.add('hidden');
      canvas.classList.remove('crosshair');
      toast(`Destination set to (${cad[0]}, ${cad[1]})`);
      draw();
      return;
    }

    // Feature selection
    const rect = canvas.getBoundingClientRect();
    const bs = getBoundsAndScale(rect);
    if (bs) {
      const list = data.features.filter(visible).map(f => ({ f, pts: featPoints(f) }));
      let best = null, dist = 14;
      for (const it of list) {
        for (const p of it.pts) {
          const q = cadToScreen(p, bs);
          const dd = Math.hypot(q[0] - e.offsetX, q[1] - e.offsetY);
          if (dd < dist) {
            dist = dd;
            best = it.f;
          }
        }
      }
      if (best) selectFeature(best);
    }
  }
  drag = null;
};

canvas.onwheel = e => {
  e.preventDefault();
  zoom = Math.max(0.15, Math.min(10, zoom * (e.deltaY < 0 ? 1.12 : 0.88)));
  $('#zoomLabel').textContent = Math.round(zoom * 100) + '%';
  draw();
};

function selectFeature(f) {
  selected = f;
  draw();
  const p = f.properties, g = f.geometry;
  $('#featureOrdinal').textContent = `${p.source_entity || 'ENTITY'} · ${p.source_handle || 'NO HANDLE'}`;
  const rows = [
    ['CATEGORY', p.category],
    ['SOURCE LAYER', p.source_layer],
    ['DXF ENTITY', p.source_entity],
    ['DISPLAY', p.display_name],
    ['TACTICAL', p.tactical ? 'YES' : 'NO'],
    ['CONFIDENCE', p.confidence || 'high'],
    ['GEOMETRY', g?.type || 'Unsupported'],
    ['COORDINATES', g?.coordinates?.flat?.().slice(0, 4).join(', ') || '—'],
    ['SOURCE HANDLE', p.source_handle || '—'],
  ];
  $('#featureDetails').innerHTML = rows
    .map(([a, b]) => `<div class="detail-item"><span>${a}</span><strong>${String(b)}</strong></div>`)
    .join('');
  $('#selectionTag').textContent = `${p.category.toUpperCase()} · ${p.source_layer} · ${p.source_entity}`;
  $('#selectionTag').classList.remove('hidden');
}

// Route Picking UI
$('#pickStartBtn').onclick = () => {
  pickMode = pickMode === 'start' ? null : 'start';
  $('#pickStartBtn').classList.toggle('active', pickMode === 'start');
  $('#pickDestBtn').classList.remove('active');
  $('#pickIndicator').classList.toggle('hidden', !pickMode);
  $('#pickIndicator').textContent = 'CLICK CANVAS: SET START';
  canvas.classList.toggle('crosshair', !!pickMode);
};

$('#pickDestBtn').onclick = () => {
  pickMode = pickMode === 'dest' ? null : 'dest';
  $('#pickDestBtn').classList.toggle('active', pickMode === 'dest');
  $('#pickStartBtn').classList.remove('active');
  $('#pickIndicator').classList.toggle('hidden', !pickMode);
  $('#pickIndicator').textContent = 'CLICK CANVAS: SET DESTINATION';
  canvas.classList.toggle('crosshair', !!pickMode);
};

$('#pickIndicator').onclick = () => {
  pickMode = null;
  $('#pickStartBtn').classList.remove('active');
  $('#pickDestBtn').classList.remove('active');
  $('#pickIndicator').classList.add('hidden');
  canvas.classList.remove('crosshair');
};

$('#startPresetBtn').onclick = () => {
  startCoord = [3000, 2500];
  $('#startCoordDisplay').value = '3000, 2500';
  toast('Start set to Room 1 (3000, 2500)');
  draw();
};

// Route Calculation
$('#planRouteBtn').onclick = async () => {
  if (!data) {
    toast('Upload a CAD drawing first.');
    return;
  }
  if (!startCoord) {
    toast('Select a start coordinate.');
    return;
  }

  const destVal = $('#destSelect').value;
  let destination;
  if (destVal === 'nearest_exit') {
    destination = 'nearest_exit';
  } else if (destVal === 'custom') {
    if (!destCoord) {
      toast('Click canvas to pick custom destination coordinate.');
      return;
    }
    destination = destCoord;
  } else {
    destination = destVal.split(',').map(Number);
  }

  const btn = $('#planRouteBtn');
  btn.disabled = true;
  btn.textContent = 'Calculating Route…';
  $('#routeStatusPill').className = 'status-pill';
  $('#routeStatusPill').innerHTML = '<i></i> ROUTING';
  $('#routeErrorMsg').classList.add('hidden');
  $('#routeResultsCard').classList.add('hidden');

  try {
    const payload = {
      collection: data,
      start: startCoord,
      destination: destination,
      hazard_mode: $('#hazardModeSelect').value,
      hazard_penalty: parseFloat($('#hazardPenaltyInput').value) || 5.0,
    };

    const res = await fetch('/api/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const routeData = await res.json();

    if (routeData.status === 'success') {
      activeRoute = routeData;
      $('#routeStatusPill').className = 'status-pill ready';
      $('#routeStatusPill').innerHTML = '<i></i> SUCCESS';
      $('#clearRouteBtn').disabled = false;

      // Telemetry
      const unitCode = data.metadata.units_code;
      const distStr = unitCode === 4
        ? `${(routeData.distance * 0.001).toFixed(1)} m (${Math.round(routeData.distance)} mm)`
        : `${routeData.distance.toFixed(1)} units`;
      $('#routeDistanceVal').textContent = distStr;
      $('#routeCostVal').textContent = routeData.cost.toFixed(1);

      const targetLabel = routeData.destination_info?.label || 'Destination';
      const targetLayer = routeData.destination_info?.layer || '';
      $('#routeTargetName').textContent = `REACHED: ${targetLabel.toUpperCase()}${targetLayer ? ' [' + targetLayer + ']' : ''}`;

      // Warnings
      const warnBox = $('#routeWarnings');
      if (routeData.warnings && routeData.warnings.length) {
        warnBox.innerHTML = routeData.warnings.map(w => `<div>⚠️ ${w}</div>`).join('');
        warnBox.classList.remove('hidden');
      } else {
        warnBox.classList.add('hidden');
      }

      // Step-by-Step Instructions
      const instList = $('#routeInstructionsList');
      instList.innerHTML = routeData.instructions.map(inst => `<li>${inst}</li>`).join('');
      $('#instructionCount').textContent = routeData.instructions.length;

      $('#routeResultsCard').classList.remove('hidden');
      toast(`Route computed: ${distStr}`);
      draw();
    } else {
      activeRoute = null;
      $('#routeStatusPill').className = 'status-pill warn';
      $('#routeStatusPill').innerHTML = `<i></i> ${routeData.status.toUpperCase()}`;
      $('#routeErrorMsg').innerHTML = `<strong>Route could not be established:</strong><br>${routeData.error || 'No valid path found through open corridors.'}`;
      $('#routeErrorMsg').classList.remove('hidden');
      toast(routeData.error || 'Destination unreachable');
      draw();
    }
  } catch (err) {
    $('#routeStatusPill').className = 'status-pill error';
    $('#routeStatusPill').innerHTML = '<i></i> ERROR';
    $('#routeErrorMsg').textContent = `Route calculation failed: ${err.message}`;
    $('#routeErrorMsg').classList.remove('hidden');
    toast(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Calculate Tactical Route';
  }
};

$('#clearRouteBtn').onclick = () => {
  activeRoute = null;
  $('#clearRouteBtn').disabled = true;
  $('#routeResultsCard').classList.add('hidden');
  $('#routeErrorMsg').classList.add('hidden');
  $('#routeStatusPill').className = 'status-pill idle';
  $('#routeStatusPill').innerHTML = '<i></i> READY';
  draw();
  toast('Route cleared');
};

// Exports & Validation
$('#geoBtn').onclick = () => download(new Blob([JSON.stringify(data, null, 2)], { type: 'application/geo+json' }), 'complete-building.geojson');

async function downloadDxf() {
  const r = await fetch('/api/reconstruct', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw Error('Reconstruction failed');
  download(await r.blob(), 'reconstructed.dxf');
}
$('#dxfBtn').onclick = () => downloadDxf().catch(e => toast(e.message));

function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

$('#validateBtn').onclick = async () => {
  const btn = $('#validateBtn');
  btn.disabled = true;
  btn.innerHTML = '<span>⟳</span> Comparing complete dataset…';
  try {
    const fd = new FormData();
    fd.append('file', sourceFile, 'source.dxf');
    const r = await fetch('/api/validate', { method: 'POST', body: fd });
    if (!r.ok) throw Error('Validation failed');
    const out = await r.json();
    renderReport(out.report);
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>⟳</span> Run round-trip check';
  }
};

function renderReport(r) {
  $('#validationPill').textContent = r.status;
  $('#validationPill').className = 'status-pill ' + (r.status === 'PASSED' ? 'ready' : r.status === 'WARNING' ? 'warn' : 'error');
  const fields = [
    ['SOURCE ENTITIES', r.original_entity_count],
    ['REBUILT ENTITIES', r.reconstructed_entity_count],
    ['MISSING / EXTRA', `${r.missing_entities} / ${r.extra_entities}`],
    ['MAX COORD. DEVIATION', Number(r.maximum_coordinate_deviation).toExponential(1)],
    ['AVG COORD. DEVIATION', Number(r.average_coordinate_deviation).toExponential(1)],
    ['BBOX MAX Δ', r.bbox_max_difference === null ? 'N/A' : Number(r.bbox_max_difference).toExponential(1)],
    ['CATEGORY MISMATCHES', r.category_mismatches],
    ['LAYER MISMATCHES', r.layer_mismatches],
    ['ENTITY TYPE CHANGES', r.entity_type_mismatches],
    ['UNSUPPORTED', r.unsupported_entity_count],
    ['DXF RECOVERY ERRORS', r.recovery_error_count],
  ];
  const counts = {
    original: { categories: r.original_category_counts, layers: r.original_layer_counts },
    reconstructed: { categories: r.reconstructed_category_counts, layers: r.reconstructed_layer_counts },
  };
  $('#reportBody').innerHTML = `
    <div class="report-grid">
      ${fields.map(([k, v]) => `<div class="report-metric"><span>${k}</span><b>${v}</b></div>`).join('')}
    </div>
    <details class="report-counts">
      <summary>Category and layer counts</summary>
      <pre>${JSON.stringify(counts, null, 2)}</pre>
    </details>
    <p class="report-message">${r.message}${r.unsupported_entity_count ? ` Unsupported: ${JSON.stringify(r.unsupported_entities)}` : ''}</p>
  `;
}

window.addEventListener('resize', draw);
