(function () {
  'use strict';

  // mobile menu
  var tog = document.querySelector('.nav-toggle'), nav = document.getElementById('nav');
  if (tog && nav) tog.addEventListener('click', function () {
    var open = nav.classList.toggle('open');
    tog.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  // maps: <div class="leaflet-map" data-points='[[lat,lon,"html"],...]'>
  window.BDLT = window.BDLT || {};
  BDLT.tiles = function (map) {
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
  };
  BDLT.drawMap = function (el, points) {
    if (!window.L) return null;
    if (el._map) { el._map.remove(); }
    var map = L.map(el, { scrollWheelZoom: false });
    el._map = map;
    BDLT.tiles(map);
    var bounds = [];
    points.forEach(function (p) {
      var m = L.marker([p[0], p[1]]).addTo(map);
      if (p[2]) m.bindPopup(p[2], { maxWidth: 360, maxHeight: 300 });
      bounds.push([p[0], p[1]]);
    });
    var z = parseInt(el.getAttribute('data-zoom') || '0', 10);
    if (bounds.length === 1) map.setView(bounds[0], z || 9);
    else if (bounds.length) map.fitBounds(bounds, { padding: [20, 20] });
    else map.setView([42.7, 25.3], 7);
    return map;
  };
  document.querySelectorAll('.leaflet-map[data-points]').forEach(function (el) {
    try { BDLT.drawMap(el, JSON.parse(el.getAttribute('data-points'))); } catch (e) { console.error(e); }
  });

  // tabs (remember choice per visitor; also honour old ?qt-text_display_public=N links)
  document.querySelectorAll('[data-tabs]').forEach(function (box) {
    var tabs = box.querySelectorAll('[role=tab]');
    function show(name) {
      tabs.forEach(function (t) { t.setAttribute('aria-selected', t.dataset.tab === name ? 'true' : 'false'); });
      box.querySelectorAll('[data-panel]').forEach(function (p) { p.hidden = p.dataset.panel !== name; });
      try { localStorage.setItem('bdlt-tab', name); } catch (e) {}
    }
    tabs.forEach(function (t) { t.addEventListener('click', function () { show(t.dataset.tab); }); });
    var m = /qt-text_display_public=(\d)/.exec(location.search), saved = null;
    try { saved = localStorage.getItem('bdlt-tab'); } catch (e) {}
    if (m) show(['glossed', 'line', 'cyrillic'][+m[1]] || 'glossed');
    else if (saved && box.querySelector('[data-tab="' + saved + '"]')) show(saved);
  });

  // audio: click a timecode to play from there; highlight the line being spoken
  var audio = document.getElementById('audio');
  if (audio) {
    var follow = document.getElementById('follow');
    document.addEventListener('click', function (e) {
      var b = e.target.closest('button.tc');
      if (!b) return;
      var t = parseFloat(b.dataset.t);
      var go = function () { audio.currentTime = t; audio.play(); };
      if (audio.readyState >= 1) go();            // metadata loaded: seek straight away
      else { audio.addEventListener('loadedmetadata', go, { once: true }); audio.load(); }
    });
    var lines = Array.prototype.slice.call(document.querySelectorAll('.line[data-t]'));
    var last = -1;
    audio.addEventListener('timeupdate', function () {
      var t = audio.currentTime, idx = -1, cur = null;
      // lines appear once per tab; work per panel, using the visible one for scrolling
      document.querySelectorAll('[data-panel]').forEach(function (panel) {
        var best = null;
        panel.querySelectorAll('.line[data-t]').forEach(function (l) {
          if (parseFloat(l.dataset.t) <= t + 0.05) best = l;
          l.classList.remove('current');
        });
        if (best) { best.classList.add('current'); if (!panel.hidden) cur = best; }
      });
      if (cur) {
        idx = lines.indexOf(cur);
        if (idx !== last && follow && follow.checked && !audio.paused) {
          var r = cur.getBoundingClientRect();
          if (r.top < 90 || r.bottom > window.innerHeight) cur.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
        last = idx;
      }
    });
  }

  // simple client-side sorting for tables with class "sortable"
  document.querySelectorAll('table.sortable').forEach(function (tbl) {
    tbl.querySelectorAll('th').forEach(function (th, i) {
      th.addEventListener('click', function () {
        var body = tbl.tBodies[0], rows = Array.prototype.slice.call(body.rows);
        var dir = th.dataset.dir === 'asc' ? -1 : 1;
        tbl.querySelectorAll('th').forEach(function (h) { delete h.dataset.dir; });
        th.dataset.dir = dir === 1 ? 'asc' : 'desc';
        rows.sort(function (a, b) {
          var x = a.cells[i].textContent.trim(), y = b.cells[i].textContent.trim();
          var nx = parseFloat(x.replace(/,/g, '')), ny = parseFloat(y.replace(/,/g, ''));
          if (!isNaN(nx) && !isNaN(ny) && /^[\d.,\s]+$/.test(x + y)) return dir * (nx - ny);
          return dir * (BDLT.collate ? BDLT.collate(x, y) : x.localeCompare(y));
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
})();
