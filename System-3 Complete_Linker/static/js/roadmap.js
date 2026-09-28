/* AntahAI Learning Pathways - interactive roadmap renderer.
 *
 * Dependency-free (no build step, works offline). The server computes the
 * graph *and* its layout (pathways/engine.py); this file only draws it:
 * HTML nodes + SVG bezier edges inside a pan/zoom "world", with fit-to-view,
 * reset, keyboard access, pinch zoom, a minimap and a detail drawer.
 */
(function () {
  'use strict';
  var I = window.PW.icons, esc = window.PW.esc;

  var SIZE = {
    start: [230, 120], course: [250, 118], assessment: [176, 64],
    lab: [196, 72], milestone: [200, 70], goal: [250, 130]
  };
  var STATE_LABEL = {
    completed: 'Completed', in_progress: 'In progress', available: 'Available',
    locked: 'Locked', unavailable: 'Unavailable'
  };
  var STATE_ICON = {
    completed: I.check, in_progress: I.half, available: I.play, locked: I.lock, unavailable: I.ban
  };
  var BASIS_LABEL = { assessment: 'Validated', self_reported: 'Self-reported', none: 'No evidence' };

  function stateBadge(state, override) {
    return '<span class="n-state">' + (STATE_ICON[state] || '') + esc(override || STATE_LABEL[state] || state) + '</span>';
  }
  function initials(name) {
    var parts = String(name || '?').replace(/\(.*?\)/g, '').trim().split(/\s+/);
    return ((parts[0] || '?')[0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
  }
  function shortName(name) {
    return String(name).replace(/ & .*$/, '').replace(/^Statistical Computing in Python$/, 'Python stats')
      .replace(/^Python Programming Fundamentals$/, 'Python basics').replace(/ Statistics$/, ' stats');
  }

  function nodeHTML(n) {
    var d = n.data || {};
    if (n.type === 'start') {
      var met = (d.levels || []).filter(function (l) { return l.current >= l.target; }).length;
      return '<div class="who"><div class="av">' + esc(initials(n.title)) + '</div><div><div class="n-sub">Starting point</div>' +
        '<div class="n-title">' + esc(n.title) + '</div></div></div>' +
        '<div class="row between"><span class="n-sub">Goal readiness</span><b style="color:var(--brand-deep);font-size:15px">' + d.readiness + '%</b></div>' +
        '<div class="progress"><span style="width:' + d.readiness + '%"></span></div>' +
        '<div class="n-sub" style="margin-top:-2px">' + met + ' of ' + (d.levels || []).length + ' goal competencies met</div>';
    }
    if (n.type === 'goal') {
      return '<div class="row between"><div class="flag">' + I.flag + '</div><div class="ring sm on-dark" style="--p:' + d.readiness + ';--c:#7CC4FF"><b>' + d.readiness + '%</b></div></div>' +
        '<div><div class="n-sub">' + (n.state === 'completed' ? 'Goal achieved' : 'Goal destination') + '</div><div class="n-title">' + esc(n.title) + '</div></div>';
    }
    if (n.type === 'course') {
      var foot;
      var p = d.progress || {};
      if (n.state === 'in_progress') {
        foot = '<div class="progress"><span style="width:' + (p.percent || 0) + '%"></span></div><b>' + (p.percent || 0) + '%</b>';
      } else if (n.state === 'locked') {
        var unmet = (d.prerequisites || []).filter(function (x) { return !x.satisfied; });
        foot = I.lock.replace('<svg', '<svg width="12" height="12"') + '<span>Needs ' + esc(unmet.map(function (x) { return shortName(x.name) + ' ≥ ' + x.min_level; }).join(', ')) + '</span>';
      } else if (n.state === 'unavailable') {
        foot = '<span>External listing · not verified</span>';
      } else if (n.state === 'completed') {
        foot = '<span style="color:var(--done);font-weight:700">Assessed · evidence recorded</span>';
      } else {
        foot = '<div class="n-comps">' + (d.develops || []).slice(0, 3).map(function (c) {
          return '<span>' + esc(shortName(c.name)) + '</span>';
        }).join('') + '</div>';
      }
      return (n.recommended ? '<span class="rec-flag">Recommended next</span>' : '') +
        '<div class="n-top">' + stateBadge(n.state) + '<span class="n-sub">' + esc(n.subtitle) + '</span></div>' +
        '<div class="n-title">' + esc(n.title) + '</div><div class="n-foot">' + foot + '</div>';
    }
    if (n.type === 'assessment' || n.type === 'lab') {
      var sub = n.type === 'assessment'
        ? (d.best_score != null ? 'Best score ' + d.best_score + '%' : (n.state === 'locked' ? 'Locked' : 'Not attempted'))
        : (n.state === 'completed' ? 'Completed' : n.state === 'locked' ? 'After assessment' : 'Ready');
      if (n.state === 'completed' && n.type === 'assessment') sub = 'Passed · ' + (d.best_score != null ? d.best_score + '%' : '');
      return '<div class="n-ico">' + (n.state === 'completed' ? I.check : n.type === 'lab' ? I.lab : I.quiz) + '</div>' +
        '<div style="min-width:0"><div class="n-title">' + esc(n.title) + '</div><div class="n-sub">' + esc(sub) + '</div></div>';
    }
    if (n.type === 'milestone') {
      var pct = Math.min(100, Math.round(100 * d.current / Math.max(1, d.target)));
      return '<div class="diamond"></div><div style="flex:1;min-width:0"><div class="n-title">' + esc(n.title) + '</div>' +
        '<div class="n-sub">' + (n.state === 'completed' ? 'Reached ' + d.current : n.state === 'unavailable' ? 'No available course' : d.current + ' / ' + d.target) + '</div>' +
        '<div class="bar"><span class="fill ' + (d.basis || 'none') + '" style="width:' + pct + '%"></span></div></div>';
    }
    return esc(n.title);
  }

  function ariaLabel(n) {
    var s = n.type === 'course' ? 'Course: ' : n.type === 'assessment' ? 'Assessment for ' + n.subtitle + ': ' :
      n.type === 'lab' ? 'Lab: ' : n.type === 'milestone' ? 'Milestone: ' : n.type === 'goal' ? 'Goal: ' : '';
    return s + n.title + '. ' + (STATE_LABEL[n.state] || n.state) + (n.recommended ? '. Recommended next.' : '');
  }

  // ------------------------------------------------------------------
  function Roadmap(canvas, opts) {
    this.canvas = canvas;
    this.opts = opts || {};
    this.t = { x: 0, y: 0, k: 1 };
    this.nodes = {}; this.els = {}; this.edgeEls = [];
    canvas.innerHTML = '<div class="rm-grid"></div><div class="rm-world"></div>';
    this.grid = canvas.querySelector('.rm-grid');
    this.world = canvas.querySelector('.rm-world');
    if (this.opts.interactive !== false) this._bind();
  }

  Roadmap.prototype.render = function (data) {
    var self = this;
    this.data = data;
    this.nodes = {};
    data.nodes.forEach(function (n) { self.nodes[n.id] = n; });
    var W = data.width, H = data.height;
    this.world.style.width = W + 'px'; this.world.style.height = H + 'px';

    var svg = ['<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true"><defs>'];
    [['a-def', '#B7C3D3'], ['a-done', '#53A677'], ['a-act', '#E85F1C'], ['a-hl', '#1573C9']].forEach(function (m) {
      svg.push('<marker id="' + m[0] + '" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 1L9 5L0 9z" fill="' + m[1] + '"/></marker>');
    });
    svg.push('</defs>');
    var halos = [], lines = [], labels = [];
    data.edges.forEach(function (e) {
      var s = self.nodes[e.source], t = self.nodes[e.target];
      if (!s || !t) return;
      var sx = s.x + SIZE[s.type][0] / 2, sy = s.y, tx = t.x - SIZE[t.type][0] / 2 - 3, ty = t.y;
      var dx = Math.max(40, (tx - sx) * 0.5);
      var d = 'M' + sx + ',' + sy + ' C' + (sx + dx) + ',' + sy + ' ' + (tx - dx) + ',' + ty + ' ' + tx + ',' + ty;
      var done = s.state === 'completed' && (t.state === 'completed' || s.type !== 'start');
      var active = t.recommended && !done;
      var dashed = e.kind === 'gap' || t.state === 'unavailable';
      var cls = 'edge' + (done ? ' done' : '') + (active ? ' active' : '') + (dashed && !active ? ' dashed' : '');
      var marker = done ? 'a-done' : active ? 'a-act' : 'a-def';
      halos.push('<path class="edge-halo" d="' + d + '"/>');
      lines.push('<path class="' + cls + '" data-edge="' + esc(e.id) + '" data-marker="' + marker + '" marker-end="url(#' + marker + ')" d="' + d + '"/>');
      if (e.label && (e.kind === 'prerequisite' || e.kind === 'gap')) {
        var mx = (sx + tx) / 2, my = (sy + ty) / 2;
        var tw = e.label.length * 5.6 + 10;
        labels.push('<g transform="translate(' + mx + ',' + my + ')"><rect class="edge-label-bg" x="' + (-tw / 2) + '" y="-9" width="' + tw + '" height="16" rx="8"/>' +
          '<text class="edge-label" text-anchor="middle" y="3">' + esc(e.label) + '</text></g>');
      }
    });
    svg.push(halos.join(''), lines.join(''), labels.join(''), '</svg>');

    var html = [svg.join('')];
    data.nodes.forEach(function (n) {
      var cls = 'node ' + n.type + ' st-' + n.state + (n.recommended ? ' recommended' : '');
      html.push('<div class="' + cls + '" data-node="' + esc(n.id) + '" role="button" tabindex="0" aria-label="' + esc(ariaLabel(n)) + '" style="left:' + n.x + 'px;top:' + n.y + 'px">' + nodeHTML(n) + '</div>');
    });
    this.world.innerHTML = html.join('');
    this.els = {};
    Array.prototype.forEach.call(this.world.querySelectorAll('[data-node]'), function (el) {
      self.els[el.getAttribute('data-node')] = el;
    });
    this.edgeEls = Array.prototype.slice.call(this.world.querySelectorAll('path.edge'));
    if (this.opts.minimap) this._buildMinimap();
    this.fit(false);
  };

  // --- transform -------------------------------------------------------
  Roadmap.prototype.apply = function (animate) {
    var w = this.world;
    if (animate) { w.classList.add('animate'); clearTimeout(this._at); this._at = setTimeout(function () { w.classList.remove('animate'); }, 480); }
    w.style.transform = 'translate(' + this.t.x + 'px,' + this.t.y + 'px) scale(' + this.t.k + ')';
    var g = 24 * this.t.k;
    this.grid.style.backgroundSize = g + 'px ' + g + 'px';
    this.grid.style.backgroundPosition = this.t.x + 'px ' + this.t.y + 'px';
    this.canvas.classList.toggle('far', this.t.k < 0.8);
    if (this.opts.onZoom) this.opts.onZoom(this.t.k);
    this._updateMinimap();
  };

  Roadmap.prototype.bounds = function () {
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (var id in this.nodes) {
      var n = this.nodes[id], s = SIZE[n.type];
      minX = Math.min(minX, n.x - s[0] / 2); maxX = Math.max(maxX, n.x + s[0] / 2);
      minY = Math.min(minY, n.y - s[1] / 2 - 14); maxY = Math.max(maxY, n.y + s[1] / 2);
    }
    return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
  };

  Roadmap.prototype.fit = function (animate) {
    var r = this.canvas.getBoundingClientRect();
    if (!r.width || !r.height || !this.data) return;
    var b = this.bounds(), pad = this.opts.compact ? 16 : 56;
    var padRight = this.drawerOpen && r.width > 760 ? 440 : 0;
    var padTop = this.opts.compact ? 0 : 44;
    var k = Math.min((r.width - padRight - pad * 2) / b.w, (r.height - padTop - pad * 2) / b.h, 1.15);
    k = Math.max(k, 0.18);
    if (!this.opts.compact && r.width < 760 && k < 0.55 && !animate) {
      // Small screens: start readable, focused on the next step (or start).
      var focus = this.data.nodes.filter(function (n) { return n.recommended; })[0] || this.nodes.start;
      return this.centerOn(focus.id, 0.72, false);
    }
    this.t.k = k;
    this.t.x = (r.width - padRight - b.w * k) / 2 - b.x * k;
    this.t.y = padTop + (r.height - padTop - b.h * k) / 2 - b.y * k;
    this.apply(animate);
  };

  Roadmap.prototype.centerOn = function (id, k, animate) {
    var n = this.nodes[id]; if (!n) return;
    var r = this.canvas.getBoundingClientRect();
    var padRight = this.drawerOpen && r.width > 760 ? 440 : 0;
    var visH = this.drawerOpen && r.width <= 760 ? r.height * 0.22 : r.height;
    this.t.k = k || this.t.k;
    this.t.x = (r.width - padRight) / 2 - n.x * this.t.k;
    this.t.y = visH / 2 - n.y * this.t.k;
    this.apply(animate);
  };

  Roadmap.prototype.reset = function () {
    var r = this.canvas.getBoundingClientRect();
    var s = this.nodes.start;
    this.t.k = 1;
    this.t.x = 40 - (s.x - SIZE.start[0] / 2);
    this.t.y = r.height / 2 - s.y;
    this.apply(true);
  };

  Roadmap.prototype.zoomBy = function (f, cx, cy, animate) {
    var r = this.canvas.getBoundingClientRect();
    if (cx == null) { cx = r.width / 2; cy = r.height / 2; }
    var k = Math.min(2.2, Math.max(0.18, this.t.k * f));
    var wx = (cx - this.t.x) / this.t.k, wy = (cy - this.t.y) / this.t.k;
    this.t.k = k;
    this.t.x = cx - wx * k; this.t.y = cy - wy * k;
    this.apply(animate);
  };

  // --- interaction -------------------------------------------------------
  Roadmap.prototype._bind = function () {
    var self = this, c = this.canvas;
    var pointers = {}, start = null, moved = false, pinch = null;

    c.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button !== 0) return;
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (ids.length === 1) {
        start = { x: e.clientX, y: e.clientY, tx: self.t.x, ty: self.t.y, node: e.target.closest('[data-node]') };
        moved = false;
      } else if (ids.length === 2) {
        var a = pointers[ids[0]], b = pointers[ids[1]];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: self.t.k };
        moved = true;
      }
      try { c.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
    });
    c.addEventListener('pointermove', function (e) {
      if (!pointers[e.pointerId]) return;
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (ids.length === 2 && pinch) {
        var a = pointers[ids[0]], b = pointers[ids[1]];
        var r = c.getBoundingClientRect();
        var d = Math.hypot(a.x - b.x, a.y - b.y);
        self.zoomBy((pinch.k * d / pinch.d) / self.t.k, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
        return;
      }
      if (!start) return;
      var dx = e.clientX - start.x, dy = e.clientY - start.y;
      if (!moved && Math.abs(dx) + Math.abs(dy) > 5) { moved = true; c.classList.add('dragging'); }
      if (moved) { self.t.x = start.tx + dx; self.t.y = start.ty + dy; self.apply(false); }
    });
    function end(e) {
      delete pointers[e.pointerId];
      if (Object.keys(pointers).length < 2) pinch = null;
      if (!start) return;
      c.classList.remove('dragging');
      if (!moved && e.type === 'pointerup') {
        if (start.node) self.select(start.node.getAttribute('data-node'));
        else self.clearSelection(true);
      }
      if (!Object.keys(pointers).length) start = null;
    }
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);
    c.addEventListener('wheel', function (e) {
      e.preventDefault();
      var r = c.getBoundingClientRect();
      var f = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018));
      self.zoomBy(f, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    c.addEventListener('dblclick', function (e) { if (!e.target.closest('[data-node]')) self.fit(true); });
    c.addEventListener('keydown', function (e) {
      var el = e.target.closest && e.target.closest('[data-node]');
      if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); self.select(el.getAttribute('data-node')); }
    });
    window.addEventListener('resize', function () { clearTimeout(self._rt); self._rt = setTimeout(function () { self.fit(false); }, 150); });
  };

  Roadmap.prototype.select = function (id) {
    if (!this.nodes[id]) return;
    if (this.selected && this.els[this.selected]) this.els[this.selected].classList.remove('selected');
    this.selected = id;
    this.els[id].classList.add('selected');
    this.clearHighlight();
    if (this.opts.onSelect) this.opts.onSelect(this.nodes[id]);
  };

  Roadmap.prototype.clearSelection = function (notify) {
    if (this.selected && this.els[this.selected]) this.els[this.selected].classList.remove('selected');
    this.selected = null;
    this.clearHighlight();
    if (notify && this.opts.onClear) this.opts.onClear();
  };

  Roadmap.prototype.ancestors = function (id) {
    var preds = {};
    this.data.edges.forEach(function (e) { (preds[e.target] = preds[e.target] || []).push(e.source); });
    var seen = {}, stack = [id];
    while (stack.length) {
      var cur = stack.pop();
      (preds[cur] || []).forEach(function (p) { if (!seen[p]) { seen[p] = true; stack.push(p); } });
    }
    return seen;
  };

  Roadmap.prototype.highlightPath = function (id) {
    var keep = this.ancestors(id); keep[id] = true;
    for (var nid in this.els) this.els[nid].classList.toggle('dim', !keep[nid]);
    var self = this;
    this.edgeEls.forEach(function (p) {
      var parts = p.getAttribute('data-edge').split('->');
      var on = keep[parts[0]] && keep[parts[1]];
      p.classList.toggle('dim', !on);
      p.classList.toggle('hl', !!on);
      p.setAttribute('marker-end', 'url(#' + (on ? 'a-hl' : p.getAttribute('data-marker')) + ')');
    });
    this._highlighted = true;
    self.fitNodes(Object.keys(keep));
  };

  Roadmap.prototype.fitNodes = function (ids) {
    var saved = this.nodes, sub = {};
    ids.forEach(function (i) { if (saved[i]) sub[i] = saved[i]; });
    this.nodes = sub; this.fit(true); this.nodes = saved;
  };

  Roadmap.prototype.clearHighlight = function () {
    if (!this._highlighted) return;
    for (var nid in this.els) this.els[nid].classList.remove('dim');
    this.edgeEls.forEach(function (p) {
      p.classList.remove('dim', 'hl');
      p.setAttribute('marker-end', 'url(#' + p.getAttribute('data-marker') + ')');
    });
    this._highlighted = false;
  };

  // --- minimap -------------------------------------------------------------
  var MINI_FILL = { completed: '#86CFA3', in_progress: '#7DB5EA', available: '#FFFFFF', locked: '#E5E7EB', unavailable: '#F1D3CC' };
  Roadmap.prototype._buildMinimap = function () {
    var host = this.opts.minimap, self = this, W = this.data.width, H = this.data.height;
    var parts = ['<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">'];
    this.data.edges.forEach(function (e) {
      var s = self.nodes[e.source], t = self.nodes[e.target];
      if (s && t) parts.push('<line x1="' + s.x + '" y1="' + s.y + '" x2="' + t.x + '" y2="' + t.y + '" stroke="#CBD5E1" stroke-width="6"/>');
    });
    this.data.nodes.forEach(function (n) {
      var s = SIZE[n.type];
      var fill = n.type === 'goal' ? '#0F4E8C' : n.recommended ? '#E85F1C' : (MINI_FILL[n.state] || '#fff');
      parts.push('<rect x="' + (n.x - s[0] / 2) + '" y="' + (n.y - s[1] / 2) + '" width="' + s[0] + '" height="' + s[1] + '" rx="16" fill="' + fill + '" stroke="#94A3B8" stroke-width="4"/>');
    });
    parts.push('<rect class="vp" x="0" y="0" width="10" height="10" rx="10"/></svg>');
    host.innerHTML = parts.join('');
    this._vp = host.querySelector('.vp');
    this._miniSvg = host.querySelector('svg');
    if (!host._bound) {
      host._bound = true;
      host.addEventListener('click', function (e) {
        var pt = self._miniSvg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
        var p = pt.matrixTransform(self._miniSvg.getScreenCTM().inverse());
        var r = self.canvas.getBoundingClientRect();
        self.t.x = r.width / 2 - p.x * self.t.k; self.t.y = r.height / 2 - p.y * self.t.k;
        self.apply(true);
      });
    }
  };
  Roadmap.prototype._updateMinimap = function () {
    if (!this._vp) return;
    var r = this.canvas.getBoundingClientRect();
    var x = -this.t.x / this.t.k, y = -this.t.y / this.t.k;
    this._vp.setAttribute('x', x); this._vp.setAttribute('y', y);
    this._vp.setAttribute('width', r.width / this.t.k); this._vp.setAttribute('height', r.height / this.t.k);
  };

  // ------------------------------------------------------------------
  // Drawer content (used by the roadmap page)
  // ------------------------------------------------------------------
  function levelBar(current, target, reaches, basis) {
    var h = '<div class="bar"><span class="fill ' + (basis || 'none') + '" style="width:' + Math.min(100, current) + '%"></span>';
    if (reaches != null && reaches > current) {
      h += '<span class="gapfill" style="left:' + current + '%;width:' + (Math.min(100, reaches) - current) + '%"></span>';
    }
    if (target != null) h += '<span class="target" style="left:' + target + '%"></span>';
    return h + '</div>';
  }
  function fmtMin(m) {
    if (!m) return 'Not specified';
    var h = Math.floor(m / 60), r = m % 60;
    return h && r ? h + ' h ' + r + ' min' : h ? h + ' h' : r + ' min';
  }
  var SCORE_LABEL = { gap_coverage: 'Gap coverage', goal_relevance: 'Goal relevance', prereq_readiness: 'Prerequisite readiness', level_fit: 'Level fit' };

  function drawer(n, ctx) {
    var d = n.data || {}, head = '', body = [], foot = [];
    var rid = ctx.roadmapId;
    var q = rid ? '?roadmap=' + rid : '';
    if (n.type === 'course') {
      var src = d.source === 'igot_mock' ? '<span class="chip bad">iGOT connector · mock</span>' : '<span class="chip brand">Curated · demo content</span>';
      head = '<div class="row" style="margin-bottom:.45rem">' + '<span class="chip ' + ({ completed: 'ok', in_progress: 'brand', locked: 'lock', unavailable: 'bad' }[n.state] || '') + '">' + esc(STATE_LABEL[n.state]) + '</span>' +
        (n.recommended ? '<span class="chip rec">Recommended next</span>' : '') + '<span class="chip">' + esc(n.subtitle) + '</span>' + src + '</div>';
      body.push('<section><p class="small" style="color:var(--ink-2)">' + esc(d.summary) + '</p></section>');
      if (d.reasons && d.reasons.length) {
        var sc = d.score;
        body.push('<section class="why"><div class="mini-title" style="color:#B54210">Why this is on your roadmap' + (d.rank ? ' · rank #' + d.rank : '') + '</div><ul class="reasons">' +
          d.reasons.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>' +
          (sc ? '<div style="margin-top:.6rem">' + Object.keys(SCORE_LABEL).map(function (k) {
            var v = Math.round(sc.components[k] * 100);
            return '<div class="score-row"><span>' + SCORE_LABEL[k] + ' <span class="muted xs">×' + Math.round(sc.weights[k] * 100) + '%</span></span><div class="bar"><span class="fill" style="width:' + v + '%"></span></div><b>' + v + '</b></div>';
          }).join('') + '<div class="xs muted" style="margin-top:.25rem">Transparent score ' + Math.round(sc.total * 100) + '/100 — prerequisites are hard rules and are never outweighed by the score.</div></div>' : '') +
          '</section>');
      }
      body.push('<section><div class="mini-title">Competencies this course develops</div>' + (d.develops || []).map(function (c) {
        return '<div class="dev-row"><span>' + esc(c.name) + '</span><span class="xs muted">now ' + c.current + ' → up to ' + c.reaches + (c.target != null ? '' : ' · not in goal') + '</span>' +
          levelBar(c.current, c.target, c.reaches, c.current ? 'self_reported' : 'none') + '</div>';
      }).join('') + '</section>');
      body.push('<section><div class="mini-title">Prerequisites</div>' + ((d.prerequisites || []).length ? d.prerequisites.map(function (p) {
        return '<div class="prq"><span class="' + (p.satisfied ? 'ok' : 'no') + '">' + (p.satisfied ? I.check : I.lock).replace('<svg', '<svg class="ico"') + '</span>' +
          esc(p.name) + ' ≥ ' + p.min_level + ' <span class="muted xs">(you: ' + p.current + ', ' + esc(BASIS_LABEL[p.basis] || p.basis) + ')</span></div>';
      }).join('') : '<div class="small muted">None</div>') + '</section>');
      if ((d.resources || []).length) body.push('<section><div class="mini-title">Further study · external, free</div>' + d.resources.map(function (r) {
        return '<div class="res-link"><a href="' + esc(r.url) + '" target="_blank" rel="noopener noreferrer">' + esc(r.title) + ' ↗</a><span class="xs muted">' + esc(r.provider) + ' · ' + esc(r.kind) + '</span></div>';
      }).join('') + '<div class="xs muted" style="margin-top:.3rem">Opens the provider’s site. Progress there is not tracked; only the AntahAI assessment updates your competency level.</div></section>');
      if ((d.outcomes || []).length) body.push('<section><div class="mini-title">Learning outcomes</div><ul class="outcomes">' + d.outcomes.map(function (o) { return '<li>' + esc(o) + '</li>'; }).join('') + '</ul></section>');
      var pr = d.progress || {};
      body.push('<section class="row between small"><span><span class="mini-title" style="display:inline">Duration</span> ' + esc(fmtMin(d.duration_minutes)) + '</span>' +
        '<span><span class="mini-title" style="display:inline">Availability</span> ' + (d.availability === 'available' ? 'Available here' : '<b style="color:var(--unav)">Unavailable</b>') + '</span></section>');
      if (n.state !== 'unavailable') body.push('<section><div class="row between small"><span class="mini-title" style="margin:0">Progress</span><b>' + (pr.percent || 0) + '%</b></div><div class="progress ' + (n.state === 'completed' ? 'done' : '') + '" style="margin-top:.35rem"><span style="width:' + (pr.percent || 0) + '%"></span></div></section>');

      var url = '/learn/' + encodeURIComponent(n.course_id) + q;
      if (n.state === 'completed') foot.push('<a class="btn btn-outline" href="' + url + '">Review course</a>');
      else if (n.state === 'in_progress') foot.push('<a class="btn btn-primary" href="' + url + '">Continue learning</a>');
      else if (n.state === 'available') foot.push('<button class="btn btn-primary" data-start="' + esc(n.course_id) + '">Start learning</button>');
      else if (n.state === 'locked') {
        foot.push('<button class="btn btn-soft" data-prereqs="' + esc(n.id) + '">View prerequisites</button>');
        foot.push('<a class="btn btn-ghost" href="' + url + '">Preview content</a>');
      } else foot.push('<button class="btn" disabled>Content unavailable</button>');
    } else if (n.type === 'assessment') {
      head = '<div class="row" style="margin-bottom:.45rem"><span class="chip ' + ({ completed: 'ok', in_progress: 'brand', locked: 'lock' }[n.state] || '') + '">' + esc(STATE_LABEL[n.state]) + '</span><span class="chip">Assessment</span></div>';
      body.push('<section><p class="small">Scored automatically against the competencies <b>' + esc(n.subtitle) + '</b> develops. Passing (70%) records <b>assessment evidence</b>; a lower score gives targeted revision instead of credit.</p></section>');
      body.push('<section class="row" style="gap:1.5rem"><div><div class="mini-title">Attempts</div><b>' + (d.attempts || 0) + '</b></div><div><div class="mini-title">Best score</div><b>' + (d.best_score != null ? d.best_score + '%' : '—') + '</b></div><div><div class="mini-title">Pass mark</div><b>70%</b></div></section>');
      if (n.state === 'locked') foot.push('<button class="btn" disabled>Locked — finish prerequisites</button>');
      else foot.push('<a class="btn ' + (n.state === 'completed' ? 'btn-outline' : 'btn-primary') + '" href="/learn/' + encodeURIComponent(n.course_id) + '/assessment' + q + '">' + (n.state === 'completed' ? 'Retake for revision' : d.attempts ? 'Retry assessment' : 'Take assessment') + '</a>');
    } else if (n.type === 'lab') {
      head = '<div class="row" style="margin-bottom:.45rem"><span class="chip ' + ({ completed: 'ok', locked: 'lock' }[n.state] || 'brand') + '">' + esc(STATE_LABEL[n.state]) + '</span><span class="chip">Practical lab</span></div>';
      body.push('<section><p class="small"><b>' + esc(n.subtitle) + '.</b> Work with a real (demonstration) survey extract; numeric answers are checked against the dataset, and completing the lab records evidence for Applied Statistical Analysis.</p></section>');
      if (n.state === 'locked') foot.push('<button class="btn" disabled>Pass the assessment first</button>');
      else foot.push('<a class="btn ' + (n.state === 'completed' ? 'btn-outline' : 'btn-primary') + '" href="/learn/' + encodeURIComponent(n.course_id) + '/lab' + q + '">' + (n.state === 'completed' ? 'Review lab' : 'Open lab') + '</a>');
    } else if (n.type === 'milestone') {
      var contributors = ctx.data.edges.filter(function (e) { return e.target === n.id; }).map(function (e) {
        var src = ctx.nodes[e.source]; return src && src.type !== 'start' ? (src.type === 'course' ? src.title : src.subtitle || src.title) : null;
      }).filter(Boolean);
      head = '<div class="row" style="margin-bottom:.45rem"><span class="chip ' + (n.state === 'completed' ? 'ok' : n.state === 'unavailable' ? 'bad' : 'lock') + '">' + (n.state === 'completed' ? 'Reached' : n.state === 'unavailable' ? 'No course available' : 'Upcoming') + '</span><span class="chip">Skill milestone</span></div>';
      body.push('<section><div class="row between small"><span>Current <b>' + d.current + '</b> <span class="basis ' + d.basis + '">' + esc(BASIS_LABEL[d.basis] || d.basis) + '</span></span><span>Target <b>' + d.target + '</b></span></div><div style="margin-top:1.2rem">' + levelBar(d.current, d.target, null, d.basis) + '</div></section>');
      body.push('<section><div class="mini-title">Reached through</div>' + (contributors.length ? '<ul class="outcomes">' + contributors.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ul>' :
        '<p class="small">No course in the catalogue can currently close this gap. It stays visible so the gap is not hidden.</p>') + '</section>');
      body.push('<section class="small muted">Milestones move only when assessment evidence (or your own updated rating) changes — never just because content was opened.</section>');
    } else if (n.type === 'start') {
      head = '<div class="row" style="margin-bottom:.45rem"><span class="chip brand">Starting point</span></div>';
      body.push('<section class="row" style="gap:1rem"><div class="ring" style="--p:' + d.readiness + '"><b>' + d.readiness + '%</b></div><p class="small">Weighted readiness for this goal from your current competency evidence.</p></section>');
      body.push('<section><div class="mini-title">Goal competencies — you vs target</div>' + (d.levels || []).map(function (l) {
        return '<div class="dev-row"><span>' + esc(l.name) + ' <span class="basis ' + l.basis + '">' + esc(BASIS_LABEL[l.basis] || l.basis) + '</span></span><span class="xs muted">' + l.current + ' / ' + l.target + '</span>' + levelBar(l.current, l.target, null, l.basis) + '</div>';
      }).join('') + '</section>');
      foot.push('<a class="btn btn-soft" href="/competencies">Update my competencies</a>');
    } else if (n.type === 'goal') {
      head = '<div class="row" style="margin-bottom:.45rem"><span class="chip ' + (n.state === 'completed' ? 'ok' : 'brand') + '">' + (n.state === 'completed' ? 'Goal achieved' : 'Destination') + '</span></div>';
      body.push('<section class="row" style="gap:1rem"><div class="ring lg" style="--p:' + d.readiness + '"><b>' + d.readiness + '%</b></div><p class="small">' + esc(d.tagline) + '</p></section>');
      var gaps = (ctx.analysis && ctx.analysis.gaps || []).filter(function (g) { return !g.met; });
      body.push('<section><div class="mini-title">' + (gaps.length ? 'Remaining gaps' : 'All requirements met') + '</div>' + gaps.map(function (g) {
        return '<div class="dev-row"><span>' + esc(g.name) + '</span><span class="xs muted">' + g.current + ' → ' + g.target + '</span>' + levelBar(g.current, g.target, null, g.basis) + '</div>';
      }).join('') + '</section>');
      if (ctx.goalUrl) foot.push('<a class="btn btn-soft" href="' + ctx.goalUrl + '">See requirements &amp; recommendations</a>');
    }
    return {
      head: head + '<h2>' + esc(n.type === 'assessment' ? 'Assessment: ' + n.subtitle : n.type === 'lab' ? n.title + ': ' + n.subtitle : n.title) + '</h2>',
      body: body.join(''), foot: foot.join('')
    };
  }

  window.PWRoadmap = { Roadmap: Roadmap, drawer: drawer, SIZE: SIZE, STATE_LABEL: STATE_LABEL };
})();
