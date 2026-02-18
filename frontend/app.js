var trackPoints = [];
var carPos = {x: 0, z: 0};
var carRenderPos = {x: 0, z: 0};
var laps = [];
var sessionActive = false;
var canvas, ctx;
var trackBounds = {minX: 0, maxX: 1, minZ: 0, maxZ: 1};
var sectorBase = 0;
var sectorColors = {1: null, 2: null, 3: null};
var activeSector = 0;
var statePollTimer = null;
var POLL_ACTIVE_MS = 300;
var POLL_IDLE_MS = 1000;

function resetLiveView() {
    trackPoints = [];
    carPos = {x: 0, z: 0};
    carRenderPos = {x: 0, z: 0};
    laps = [];
    sectorColors = {1: null, 2: null, 3: null};
    activeSector = 0;
    sectorBase = 0;
    trackBounds = {minX: 0, maxX: 1, minZ: 0, maxZ: 1};
    window._carTrail = null;

    document.getElementById('speedVal').textContent = '0';
    document.getElementById('gearVal').textContent = 'N';
    document.getElementById('lapVal').textContent = '--';
    document.getElementById('deltaDisplay').textContent = '--';
    document.getElementById('deltaDisplay').className = 'delta-display delta-neutral';
    document.getElementById('lapList').innerHTML = '';
    document.getElementById('fastestLapNo').textContent = '--';
    document.getElementById('fastestLapVal').textContent = '--:--.---';
    renderSectorBoxes();
}

function init() {
    canvas = document.getElementById('trackCanvas');
    ctx = canvas.getContext('2d');
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    requestAnimationFrame(drawLoop);
    pollState();
    connectSocket();
}

function resizeCanvas() {
    var rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width - 16;
    canvas.height = rect.height - 60;
}

function connectSocket() {
    try {
        if (typeof io !== 'function') {
            console.warn('Socket.IO unavailable, using polling only.');
            return;
        }

        var socket = io({transports: ['websocket', 'polling']});
        socket.on('connect', function() { console.log('Connected'); });

        socket.on('telemetry', function(data) {
            applyTelemetry(data);
        });

        socket.on('track_outline', function(data) {
            trackPoints = data.points || [];
            computeTrackBounds();
        });

        socket.on('sector_color', function(data) {
            if (data && data.sector && data.color !== undefined) {
                sectorColors[data.sector] = data.color;
                renderSectorBoxes();
            }
        });

        socket.on('lap_update', function(data) {
            laps = data.laps || [];
            renderLaps();
            applyFastest(data.fastest_lap || null);
            if (data.sector_colors) {
                sectorColors = normalizeSectorColors(data.sector_colors);
                renderSectorBoxes();
            }
        });

        socket.on('session_state', function(data) {
            sessionActive = !!data.active;
            updateButtons();
            if (data.track_outline && data.track_outline.length > 0) {
                trackPoints = data.track_outline;
                computeTrackBounds();
            }
            if (data.laps) {
                laps = data.laps;
                renderLaps();
            }
            applyFastest(data.fastest_lap || null);
            if (data.sector_colors) {
                sectorColors = normalizeSectorColors(data.sector_colors);
                renderSectorBoxes();
            }
        });
    } catch (err) {
        console.warn('Socket init failed, using polling only.', err);
    }
}

function normalizeSectorColors(colors) {
    return {
        1: colors[1] || colors['1'] || null,
        2: colors[2] || colors['2'] || null,
        3: colors[3] || colors['3'] || null,
    };
}

function applyTelemetry(data) {
    if (typeof data.x === 'number' && typeof data.z === 'number') {
        carPos = {x: data.x, z: data.z};
        if (carRenderPos.x === 0 && carRenderPos.z === 0) {
            carRenderPos = {x: data.x, z: data.z};
        }
    }

    var speed = typeof data.speed === 'number' ? data.speed : 0;
    var gear = typeof data.gear === 'number' ? data.gear : 0;
    var lap = typeof data.lap === 'number' ? data.lap : 0;
    var delta = typeof data.delta === 'number' ? data.delta : 0;
    var sector = typeof data.sector === 'number' ? data.sector : 0;

    document.getElementById('speedVal').textContent = Math.round(speed);
    if (gear === 0) {
        document.getElementById('gearVal').textContent = 'N';
    } else if (gear === -1) {
        document.getElementById('gearVal').textContent = 'R';
    } else {
        document.getElementById('gearVal').textContent = gear;
    }
    document.getElementById('lapVal').textContent = lap > 0 ? 'L' + lap : 'OUT';

    var deltaEl = document.getElementById('deltaDisplay');
    if (delta !== 0) {
        var d = delta.toFixed(2);
        if (delta > 0) {
            deltaEl.textContent = '+' + d;
            deltaEl.className = 'delta-display delta-positive';
        } else {
            deltaEl.textContent = d;
            deltaEl.className = 'delta-display delta-negative';
        }
    } else {
        deltaEl.textContent = '--';
        deltaEl.className = 'delta-display delta-neutral';
    }

    if (data.sector_colors) {
        sectorColors = normalizeSectorColors(data.sector_colors);
    }

    if (data.fastest_lap) {
        applyFastest(data.fastest_lap);
    }

    if (sector === 0) sectorBase = 0;
    if (sector === 3) sectorBase = 1;
    if (sectorBase === 1) {
        if (sector >= 1 && sector <= 3) activeSector = sector;
    } else {
        if (sector >= 0 && sector <= 2) activeSector = sector + 1;
    }

    renderSectorBoxes();
}

function renderSectorBoxes() {
    for (var i = 1; i <= 3; i++) {
        var box = document.getElementById('sd' + i);
        box.className = 'sector-box';
        var color = sectorColors[i];
        if (color === 'purple') box.classList.add('s-purple');
        else if (color === 'green') box.classList.add('s-green');
        else if (color === 'yellow') box.classList.add('s-yellow');
        if (i === activeSector) box.classList.add('s-active');
    }
}

function applyFastest(fastest) {
    var noEl = document.getElementById('fastestLapNo');
    var valEl = document.getElementById('fastestLapVal');

    if (!sessionActive) {
        noEl.textContent = '--';
        valEl.textContent = '--:--.---';
        return;
    }

    if (fastest && typeof fastest.time === 'number' && fastest.time > 0) {
        noEl.textContent = 'L' + fastest.lap_num;
        valEl.textContent = formatTime(fastest.time);
    } else {
        noEl.textContent = '--';
        valEl.textContent = '--:--.---';
    }
}

function computeTrackBounds() {
    if (trackPoints.length == 0) return;
    var xs = trackPoints.map(function(p) { return p[0]; });
    var zs = trackPoints.map(function(p) { return p[1]; });
    trackBounds.minX = Math.min.apply(null, xs);
    trackBounds.maxX = Math.max.apply(null, xs);
    trackBounds.minZ = Math.min.apply(null, zs);
    trackBounds.maxZ = Math.max.apply(null, zs);
}

function worldToCanvas(x, z) {
    var pad = 20;
    var w = canvas.width - pad * 2;
    var h = canvas.height - pad * 2;
    var rangeX = trackBounds.maxX - trackBounds.minX || 1;
    var rangeZ = trackBounds.maxZ - trackBounds.minZ || 1;
    var scale = Math.min(w / rangeX, h / rangeZ);
    var cx = pad + (w - rangeX * scale) / 2 + (x - trackBounds.minX) * scale;
    var cy = pad + (h - rangeZ * scale) / 2 + (z - trackBounds.minZ) * scale;
    return {x: cx, y: cy};
}

function drawLoop() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (trackPoints.length > 2) {
        ctx.beginPath();
        ctx.strokeStyle = '#333366';
        ctx.lineWidth = 3;
        var p0 = worldToCanvas(trackPoints[0][0], trackPoints[0][1]);
        ctx.moveTo(p0.x, p0.y);
        var step = Math.max(1, Math.floor(trackPoints.length / 500));
        for (var i = step; i < trackPoints.length; i += step) {
            var p = worldToCanvas(trackPoints[i][0], trackPoints[i][1]);
            ctx.lineTo(p.x, p.y);
        }
        ctx.closePath();
        ctx.stroke();
    }

    if (carPos.x != 0 || carPos.z != 0) {
        carRenderPos.x += (carPos.x - carRenderPos.x) * 0.22;
        carRenderPos.z += (carPos.z - carRenderPos.z) * 0.22;

        if (trackPoints.length == 0) {
            if (!window._carTrail) window._carTrail = [];
            var trail = window._carTrail;
            if (trail.length == 0 || Math.abs(carRenderPos.x - trail[trail.length - 1][0]) > 2 || Math.abs(carRenderPos.z - trail[trail.length - 1][1]) > 2) {
                trail.push([carRenderPos.x, carRenderPos.z]);
            }
            if (trail.length == 1) {
                trackBounds.minX = trail[0][0] - 50;
                trackBounds.maxX = trail[0][0] + 50;
                trackBounds.minZ = trail[0][1] - 50;
                trackBounds.maxZ = trail[0][1] + 50;
            }
            if (trail.length > 1) {
                var xs = trail.map(function(p){ return p[0]; });
                var zs = trail.map(function(p){ return p[1]; });
                trackBounds.minX = Math.min.apply(null, xs) - 50;
                trackBounds.maxX = Math.max.apply(null, xs) + 50;
                trackBounds.minZ = Math.min.apply(null, zs) - 50;
                trackBounds.maxZ = Math.max.apply(null, zs) + 50;
                ctx.beginPath();
                ctx.strokeStyle = '#222244';
                ctx.lineWidth = 2;
                var t0 = worldToCanvas(trail[0][0], trail[0][1]);
                ctx.moveTo(t0.x, t0.y);
                for (var ti = 1; ti < trail.length; ti++) {
                    var tp = worldToCanvas(trail[ti][0], trail[ti][1]);
                    ctx.lineTo(tp.x, tp.y);
                }
                ctx.stroke();
            }
        } else {
            window._carTrail = null;
        }

        var cp = worldToCanvas(carRenderPos.x, carRenderPos.z);
        ctx.beginPath();
        ctx.fillStyle = '#ff3d00';
        ctx.shadowColor = '#ff3d00';
        ctx.shadowBlur = 8;
        ctx.arc(cp.x, cp.y, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
    }

    requestAnimationFrame(drawLoop);
}

function renderLaps() {
    var list = document.getElementById('lapList');
    var html = '';
    for (var i = 0; i < laps.length; i++) {
        var l = laps[i];
        var timeStr = formatTime(l.time);
        var statusHtml = '';
        if (l.is_pb) {
            statusHtml = '<span class="lap-status pb">PB</span>';
        } else if (l.valid) {
            statusHtml = '<span class="lap-status valid">&#10003;</span>';
        } else {
            statusHtml = '<span class="lap-status invalid">&#10007;</span>';
        }
        html += '<div class="lap-row"><span class="lap-num">L' + l.lap_num + '</span>'
              + '<span class="lap-time">' + timeStr + '</span>' + statusHtml + '</div>';
    }
    list.innerHTML = html;
    list.scrollTop = list.scrollHeight;
}

function formatTime(t) {
    if (t <= 0) return '--:--.---';
    var mins = Math.floor(t / 60);
    var secs = t % 60;
    var s = secs.toFixed(3);
    if (secs < 10) s = '0' + s;
    return mins + ':' + s;
}

function startMode(mode) {
    fetch('/start/' + mode, {method: 'POST'}).then(function(r) { return r.json(); })
    .then(function(d) {
        if (d.ok) {
            sessionActive = true;
            updateButtons();
            pollState();
        }
    });
}

function endSession() {
    fetch('/stop', {method: 'POST'}).then(function(r) { return r.json(); })
    .then(function() {
        sessionActive = false;
        resetLiveView();
        updateButtons();
        setTimeout(pollState, 500);
    });
}

function showAnalyze() {
    alert('Use the PC terminal to analyze sessions.');
}

function updateButtons() {
    document.getElementById('btnCoach').style.display = sessionActive ? 'none' : '';
    document.getElementById('btnLog').style.display = sessionActive ? 'none' : '';
    document.getElementById('btnAnalyze').style.display = sessionActive ? 'none' : '';
    var stopBtn = document.getElementById('btnStop');
    stopBtn.style.display = '';
    stopBtn.disabled = !sessionActive;
    stopBtn.style.opacity = sessionActive ? '1' : '0.55';
}

function pollState() {
    if (statePollTimer) {
        clearTimeout(statePollTimer);
        statePollTimer = null;
    }

    fetch('/state').then(function(r) { return r.json(); }).then(function(d) {
        var wasActive = sessionActive;
        sessionActive = !!d.active;
        updateButtons();
        if (wasActive && !sessionActive) {
            resetLiveView();
        }
        applyTelemetry(d);
        if (d.track_outline && d.track_outline.length > 0) {
            trackPoints = d.track_outline;
            computeTrackBounds();
        }
        if (d.laps) {
            laps = d.laps;
            renderLaps();
        }
        applyFastest(d.fastest_lap || null);
        if (d.sector_colors) {
            sectorColors = normalizeSectorColors(d.sector_colors);
            renderSectorBoxes();
        }
        var nextMs = sessionActive ? POLL_ACTIVE_MS : POLL_IDLE_MS;
        if (!wasActive && sessionActive) {
            nextMs = 120;
        }
        statePollTimer = setTimeout(pollState, nextMs);
    }).catch(function(){
        statePollTimer = setTimeout(pollState, POLL_IDLE_MS);
    });
}

init();
