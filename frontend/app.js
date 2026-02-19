var trackPoints = [];
var heatmapPoints = [];
var referenceBins = [];
var currentLapBins = [];
var segmentDeltas = [];
var lastLapSegmentDeltas = [];

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

var compareEnabled = true;
var compareSource = 'current';

function resetLiveView() {
    trackPoints = [];
    heatmapPoints = [];
    referenceBins = [];
    currentLapBins = [];
    segmentDeltas = [];
    lastLapSegmentDeltas = [];

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
    document.getElementById('optimalLapVal').textContent = '--:--.---';
    document.getElementById('optimalGainVal').textContent = '--';

    renderTimeLosses([]);
    renderConsistency({});
    renderProfile({tags: []});
    renderSkills({});
    renderCornerMastery([]);
    renderSectorBoxes();
}

function init() {
    canvas = document.getElementById('trackCanvas');
    ctx = canvas.getContext('2d');
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    var compareToggle = document.getElementById('compareToggle');
    var compareSourceEl = document.getElementById('compareSource');
    if (compareToggle) {
        compareToggle.addEventListener('change', function() {
            compareEnabled = !!compareToggle.checked;
        });
    }
    if (compareSourceEl) {
        compareSourceEl.addEventListener('change', function() {
            compareSource = compareSourceEl.value === 'last' ? 'last' : 'current';
        });
    }

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
            applyPerformanceData(data);
        });

        socket.on('session_state', function(data) {
            sessionActive = !!data.active;
            updateButtons();
            applyTelemetry(data);
            applyPerformanceData(data);
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

function applyPerformanceData(data) {
    if (data.track_outline && data.track_outline.length > 0) {
        trackPoints = data.track_outline;
    }
    if (data.heatmap_points && data.heatmap_points.length > 0) {
        heatmapPoints = data.heatmap_points;
    }
    if (data.reference_bins) {
        referenceBins = data.reference_bins;
    }
    if (data.current_lap_bins) {
        currentLapBins = data.current_lap_bins;
    }
    if (data.segment_deltas) {
        segmentDeltas = data.segment_deltas;
    }
    if (data.last_lap_segment_deltas) {
        lastLapSegmentDeltas = data.last_lap_segment_deltas;
    }

    renderTimeLosses(data.time_loss_summary || []);
    renderConsistency(data.consistency || {});
    renderProfile(data.driver_profile || {tags: []});
    renderSkills(data.skill_scores || {});
    renderCornerMastery(data.corner_mastery || []);
    renderOptimalLap(data.optimal_lap || null);

    computeTrackBounds();
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

function renderTimeLosses(summary) {
    var el = document.getElementById('timeLossList');
    if (!summary || summary.length === 0) {
        el.innerHTML = '<div class="kv-row"><span>No major losses</span><span>--</span></div>';
        return;
    }

    var html = '';
    for (var i = 0; i < summary.length; i++) {
        var item = summary[i];
        var deltaTxt = (typeof item.delta === 'number') ? ('+' + item.delta.toFixed(3) + 's') : '--';
        html += '<div class="kv-row"><span>T' + item.turn + ' - ' + escapeHtml(item.reason || 'Time loss') + '</span>'
             + '<span>' + deltaTxt + '</span></div>';
    }
    el.innerHTML = html;
}

function renderConsistency(consistency) {
    var lapSigma = consistency && typeof consistency.lap_sigma === 'number' ? consistency.lap_sigma : null;
    var mostIn = consistency ? consistency.most_inconsistent_corner : null;
    var mostCo = consistency ? consistency.most_consistent_corner : null;

    document.getElementById('lapSigmaVal').textContent = lapSigma !== null ? (lapSigma.toFixed(3) + 's') : '--';
    document.getElementById('mostInconsistentVal').textContent = mostIn ? ('T' + mostIn.turn + ' (' + mostIn.sigma.toFixed(3) + ')') : '--';
    document.getElementById('mostConsistentVal').textContent = mostCo ? ('T' + mostCo.turn + ' (' + mostCo.sigma.toFixed(3) + ')') : '--';
}

function renderProfile(profile) {
    var tagsEl = document.getElementById('profileTags');
    var tags = (profile && profile.tags) ? profile.tags : [];
    if (!tags || tags.length === 0) {
        tagsEl.innerHTML = '<span class="tag-pill muted">Collecting data</span>';
        return;
    }
    var html = '';
    for (var i = 0; i < tags.length; i++) {
        html += '<span class="tag-pill">' + escapeHtml(tags[i]) + '</span>';
    }
    tagsEl.innerHTML = html;
}

function renderSkills(skills) {
    var el = document.getElementById('skillBars');
    var names = Object.keys(skills || {});
    if (names.length === 0) {
        el.innerHTML = '<div class="kv-row"><span>Waiting for laps</span><span>--</span></div>';
        return;
    }

    var html = '';
    for (var i = 0; i < names.length; i++) {
        var name = names[i];
        var score = Number(skills[name]);
        if (!isFinite(score)) score = 0;
        if (score < 0) score = 0;
        if (score > 100) score = 100;

        html += '<div class="skill-row">'
             + '<div class="skill-name"><span>' + escapeHtml(name) + '</span><span>' + score.toFixed(0) + '</span></div>'
             + '<div class="skill-bar-wrap"><div class="skill-bar" style="width:' + score.toFixed(1) + '%"></div></div>'
             + '</div>';
    }
    el.innerHTML = html;
}

function renderCornerMastery(mastery) {
    var el = document.getElementById('cornerMasteryList');
    if (!mastery || mastery.length === 0) {
        el.innerHTML = '<div class="kv-row"><span>No corner data</span><span>--</span></div>';
        return;
    }

    var sorted = mastery.slice().sort(function(a, b) { return a.turn - b.turn; });
    var html = '';
    for (var i = 0; i < sorted.length; i++) {
        var row = sorted[i];
        var trend = Number(row.trend || 0);
        var trendCls = 'trend-flat';
        var trendTxt = '-';
        if (trend > 0.01) {
            trendCls = 'trend-up';
            trendTxt = 'up';
        } else if (trend < -0.01) {
            trendCls = 'trend-down';
            trendTxt = 'down';
        }
        html += '<div class="mastery-row">'
             + '<span>T' + row.turn + '</span>'
             + '<span>' + Number(row.score || 0).toFixed(0) + '</span>'
             + '<span class="' + trendCls + '">' + trendTxt + '</span>'
             + '</div>';
    }
    el.innerHTML = html;
}

function renderOptimalLap(optimal) {
    var lapEl = document.getElementById('optimalLapVal');
    var gainEl = document.getElementById('optimalGainVal');

    if (!optimal) {
        lapEl.textContent = '--:--.---';
        gainEl.textContent = '--';
        return;
    }

    var best = null;
    if (typeof optimal.bins_best === 'number') {
        best = optimal.bins_best;
    } else if (typeof optimal.sectors_best === 'number') {
        best = optimal.sectors_best;
    }

    if (best !== null) {
        lapEl.textContent = formatTime(best);
    } else {
        lapEl.textContent = '--:--.---';
    }

    var gain = null;
    if (typeof optimal.gain_vs_pb_bins === 'number') {
        gain = optimal.gain_vs_pb_bins;
    } else if (typeof optimal.gain_vs_pb_sectors === 'number') {
        gain = optimal.gain_vs_pb_sectors;
    }

    if (gain !== null) {
        gainEl.textContent = gain >= 0 ? ('-' + gain.toFixed(3) + 's') : ('+' + Math.abs(gain).toFixed(3) + 's');
    } else {
        gainEl.textContent = '--';
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
    var source = getPrimaryTrackPoints();
    if (source.length === 0) return;

    var xs = source.map(function(p) { return p[0]; });
    var zs = source.map(function(p) { return p[1]; });
    trackBounds.minX = Math.min.apply(null, xs);
    trackBounds.maxX = Math.max.apply(null, xs);
    trackBounds.minZ = Math.min.apply(null, zs);
    trackBounds.maxZ = Math.max.apply(null, zs);
}

function getPrimaryTrackPoints() {
    if (trackPoints.length > 0) return trackPoints;
    if (heatmapPoints.length > 0) return heatmapPoints;
    return [];
}

function getHeatmapPathPoints() {
    if (heatmapPoints.length > 1) return heatmapPoints;
    if (trackPoints.length > 1) return trackPoints;
    if (window._carTrail && window._carTrail.length > 1) return window._carTrail;
    return [];
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

function deltaToColor(delta) {
    if (typeof delta !== 'number' || !isFinite(delta)) return '#344062';

    if (delta < -0.02) {
        var fastMag = Math.min(Math.abs(delta), 0.45);
        var fastT = fastMag / 0.45;
        var g = Math.round(160 + fastT * 90);
        var r = Math.round(30 + fastT * 20);
        return 'rgb(' + r + ',' + g + ',70)';
    }

    if (delta > 0.02) {
        var slowMag = Math.min(delta, 0.45);
        var slowT = slowMag / 0.45;
        var rr = Math.round(210 + slowT * 40);
        var gg = Math.round(170 - slowT * 120);
        return 'rgb(' + rr + ',' + gg + ',60)';
    }

    return '#9ca3af';
}

function drawHeatmapOverlay() {
    if (!compareEnabled) return;

    var deltas = compareSource === 'last' ? lastLapSegmentDeltas : segmentDeltas;
    if (!deltas || deltas.length < 2) return;

    var path = getHeatmapPathPoints();
    if (!path || path.length < 2) return;

    var pathLen = path.length;
    for (var i = 1; i < pathLen; i++) {
        var idx = Math.floor((i / (pathLen - 1)) * (deltas.length - 1));
        var d = deltas[idx];
        if (typeof d !== 'number' || !isFinite(d)) continue;

        var p0 = worldToCanvas(path[i - 1][0], path[i - 1][1]);
        var p1 = worldToCanvas(path[i][0], path[i][1]);
        ctx.beginPath();
        ctx.strokeStyle = deltaToColor(d);
        ctx.lineWidth = 4;
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
        ctx.stroke();
    }
}

function drawLoop() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    var primary = getPrimaryTrackPoints();
    if (primary.length > 2) {
        ctx.beginPath();
        ctx.strokeStyle = '#333366';
        ctx.lineWidth = 3;
        var p0 = worldToCanvas(primary[0][0], primary[0][1]);
        ctx.moveTo(p0.x, p0.y);
        var step = Math.max(1, Math.floor(primary.length / 500));
        for (var i = step; i < primary.length; i += step) {
            var p = worldToCanvas(primary[i][0], primary[i][1]);
            ctx.lineTo(p.x, p.y);
        }
        ctx.closePath();
        ctx.stroke();
    }

    drawHeatmapOverlay();

    if (carPos.x !== 0 || carPos.z !== 0) {
        carRenderPos.x += (carPos.x - carRenderPos.x) * 0.22;
        carRenderPos.z += (carPos.z - carRenderPos.z) * 0.22;

        if (primary.length === 0) {
            if (!window._carTrail) window._carTrail = [];
            var trail = window._carTrail;
            if (trail.length === 0 || Math.abs(carRenderPos.x - trail[trail.length - 1][0]) > 2 || Math.abs(carRenderPos.z - trail[trail.length - 1][1]) > 2) {
                trail.push([carRenderPos.x, carRenderPos.z]);
            }
            if (trail.length === 1) {
                trackBounds.minX = trail[0][0] - 50;
                trackBounds.maxX = trail[0][0] + 50;
                trackBounds.minZ = trail[0][1] - 50;
                trackBounds.maxZ = trail[0][1] + 50;
            }
            if (trail.length > 1) {
                var xs = trail.map(function(pnt){ return pnt[0]; });
                var zs = trail.map(function(pnt){ return pnt[1]; });
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
    if (!isFinite(t) || t <= 0) return '--:--.---';
    var mins = Math.floor(t / 60);
    var secs = t % 60;
    var s = secs.toFixed(3);
    if (secs < 10) s = '0' + s;
    return mins + ':' + s;
}

function escapeHtml(str) {
    return String(str || '').replace(/[&<>\"]/g, function(ch) {
        if (ch === '&') return '&amp;';
        if (ch === '<') return '&lt;';
        if (ch === '>') return '&gt;';
        if (ch === '"') return '&quot;';
        return ch;
    });
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
        applyPerformanceData(d);

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
    }).catch(function() {
        statePollTimer = setTimeout(pollState, POLL_IDLE_MS);
    });
}

init();