/* AntahAI Learning Pathways - browser demo app.
 * Same pages and rules as the Flask app (System-3 /pathways), but state lives
 * in this browser (localStorage when available, otherwise memory only). */
(function () {
  'use strict';
  var D = window.PW_DATA, E = window.PWEngine, I = PW.icons, esc = PW.esc;
  var COMPS = {}; D.competencies.forEach(function (c) { COMPS[c.id] = c; });
  var GOALS = {}; D.goals.forEach(function (g) { GOALS[g.id] = g; });
  var COURSE_FULL = {}; D.courses.concat(D.external_listings).forEach(function (c) { COURSE_FULL[c.id] = c; });
  var COURSES = D.courses.map(engineCourse).concat(D.external_listings.map(function (c) {
    return engineCourse(Object.assign({}, c, { source: 'igot_mock', availability: 'unavailable', duration_verified: false }));
  }));
  var COURSE = {}; COURSES.forEach(function (c) { COURSE[c.id] = c; });
  var BASIS = { assessment: 'Validated', self_reported: 'Self-reported', none: 'No evidence', resume_inferred: 'Resume suggestion' };
  var STORE_KEY = 'antahai-demo-v1';

  function engineCourse(c) {
    return { id: c.id, title: c.title, summary: c.summary || '', outcomes: c.outcomes || [], difficulty: c.difficulty,
      duration_minutes: c.duration_minutes, duration_verified: !!c.duration_verified, availability: c.availability || 'available',
      source: c.source || 'local', develops: Object.assign({}, c.develops), prerequisites: (c.prerequisites || []).map(function (p) { return { competency: p.competency, min_level: p.min_level }; }),
      has_quiz: !!(c.quiz && c.quiz.questions && c.quiz.questions.length), has_lab: !!c.lab, lab_title: (c.lab || {}).title || '' };
  }
  function now() { return new Date().toISOString().slice(0, 19) + '+00:00'; }

  // ------------------------------------------------------------------ state
  var S;
  function freshLearner(name, demo) {
    return { display_name: name, profile: { organization: '', experience_years: demo ? demo.experience_years : null, education: demo ? demo.education : '', interests: demo ? demo.interests : '' },
      is_demo: !!demo, evidence: [], enrollments: {}, attempts: [], labs: [], roadmaps: {} };
  }
  function seedDemo(d) {
    var L = freshLearner(d.display_name, d);
    d.evidence.forEach(function (e) { addEvidence(L, e.competency, e.source, e.level, e.note || 'Demo learner self-rating (demonstration data).', 'demo_seed'); });
    return L;
  }
  function initState() {
    S = { seq: 1, current: null, users: {} };
    D.demo_learners.forEach(function (d) { S.users[d.username] = seedDemo(d); });
  }
  function load() {
    try { var raw = localStorage.getItem(STORE_KEY); if (raw) { S = JSON.parse(raw); return; } } catch (e) { /* storage unavailable */ }
    initState();
  }
  function save() { try { localStorage.setItem(STORE_KEY, JSON.stringify(S)); } catch (e) { /* memory only */ } }
  function me() { return S.users[S.current]; }
  function addEvidence(L, comp, source, level, note, origin, confirmed) {
    var id = (S ? S.seq++ : Math.floor(Math.random() * 1e9));
    L.evidence.push({ id: id, competency: comp, source: source, level: level | 0, confidence: E.CONFIDENCE[source], confirmed: confirmed ? 1 : 0, note: note || '', origin: origin || '', created_at: now() });
    return id;
  }

  // ------------------------------------------------------------------ service (mirrors pathways/service.py)
  function levels(L) { return E.effectiveLevels(L.evidence); }
  function progress(L) {
    var out = {};
    Object.keys(L.enrollments).forEach(function (cid) {
      var e = L.enrollments[cid], c = COURSE[cid], full = COURSE_FULL[cid];
      var atts = L.attempts.filter(function (a) { return a.course_id === cid; });
      var qp = atts.some(function (a) { return a.result.passed; }), lp = L.labs.some(function (l) { return l.course_id === cid && l.result.passed; });
      var steps = (full.lessons || []).length + 1 + (c.has_lab ? 1 : 0);
      var done = e.lessons_done.length + (qp ? 1 : 0) + (lp ? 1 : 0);
      out[cid] = { status: e.status, percent: e.status === 'completed' ? 100 : E.pyRound(100 * done / Math.max(1, steps)),
        lessons_done: e.lessons_done, quiz_attempts: atts.length, quiz_passed: qp,
        best_score: atts.length ? Math.max.apply(null, atts.map(function (a) { return a.result.percent; })) : null,
        lab_passed: lp, started_at: e.started_at, completed_at: e.completed_at };
    });
    return out;
  }
  function generateRoadmap(L, goalId) {
    var prev = L.roadmaps[goalId], pc = [], pe = [];
    if (prev) {
      pc = prev.graph.nodes.filter(function (n) { return n.type === 'course'; }).map(function (n) { return n.course_id; });
      var cOf = {}; prev.graph.nodes.forEach(function (n) { if (n.course_id) cOf[n.id] = n.course_id; });
      prev.graph.edges.forEach(function (e) { if (e.kind === 'prerequisite' && cOf[e.source] && cOf[e.target] && cOf[e.source] !== cOf[e.target]) pe.push([cOf[e.source], cOf[e.target]]); });
    }
    var g = E.buildRoadmap(GOALS[goalId], COURSES, levels(L), progress(L), COMPS, null, pc, pe, L.display_name);
    L.roadmaps[goalId] = { goal_id: goalId, version: prev ? prev.version + 1 : 1, created_at: prev ? prev.created_at : now(), updated_at: now(), graph: g };
    return L.roadmaps[goalId];
  }
  function refreshAll(L) { Object.keys(L.roadmaps).forEach(function (gid) { generateRoadmap(L, gid); }); }
  function listRoadmaps(L) {
    return Object.keys(L.roadmaps).map(function (gid) {
      var r = L.roadmaps[gid], s = r.graph.summary, g = GOALS[gid];
      return { id: gid, goal_id: gid, goal_title: g.title, goal_tagline: g.tagline, goal_icon: g.icon, version: r.version,
        progress: s.progress, readiness: s.readiness, next_action: s.next_action, updated_at: r.updated_at };
    }).sort(function (a, b) { return a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0; });
  }
  function courseForLearner(L, cid) {
    var full = COURSE_FULL[cid]; if (!full) return null;
    var c = Object.assign({}, COURSE[cid]), lv = levels(L);
    c.lessons = full.lessons || []; c.quiz = full.quiz || null; c.lab = full.lab || null;
    c.questions = c.quiz ? c.quiz.questions : [];
    c.prereq_status = E.prerequisiteStatus(c, lv, COMPS);
    c.locked = c.prereq_status.some(function (p) { return !p.satisfied; });
    c.progress = progress(L)[cid] || { status: 'not_started', percent: 0, lessons_done: [], quiz_passed: false, lab_passed: false, quiz_attempts: 0, best_score: null };
    c.develops_named = Object.keys(c.develops).map(function (k) { return { competency: k, name: COMPS[k].name, reaches: c.develops[k], current: E.levelOf(lv, k), basis: E.basisOf(lv, k) }; });
    return c;
  }
  function ensureStartable(c) {
    if (c.availability !== 'available') throw new Error('This course is not available: its content has not been verified.');
    if (c.locked && c.progress.status === 'not_started') throw new Error('Prerequisites not met: ' + c.prereq_status.filter(function (p) { return !p.satisfied; })
      .map(function (p) { return p.name + ' ≥ ' + p.min_level + ' (you: ' + p.current + ')'; }).join('; ') + '.');
  }
  function startCourse(L, cid) {
    var c = courseForLearner(L, cid); ensureStartable(c);
    if (c.progress.status === 'not_started') { L.enrollments[cid] = { status: 'in_progress', lessons_done: [], started_at: now(), completed_at: null }; refreshAll(L); save(); }
  }
  function markLesson(L, cid, lid) {
    startCourse(L, cid);
    var e = L.enrollments[cid];
    if (e.lessons_done.indexOf(lid) < 0) { e.lessons_done.push(lid); refreshAll(L); save(); }
  }
  function completeIfDone(L, c) {
    var p = progress(L)[c.id] || {};
    if (p.quiz_passed && (!c.lab || p.lab_passed)) { var e = L.enrollments[c.id]; if (e.status !== 'completed') { e.status = 'completed'; e.completed_at = now(); } return true; }
    return false;
  }
  function levelChanges(b, a) {
    return Object.keys(COMPS).filter(function (k) { var x = b[k] || {}, y = a[k] || {}; return x.level !== y.level || x.basis !== y.basis; })
      .map(function (k) { var x = b[k] || {}, y = a[k] || {}; return { competency: k, name: COMPS[k].name, before: x.level || 0, before_basis: x.basis || 'none', after: y.level || 0, after_basis: y.basis || 'none' }; });
  }
  function snapshot(L) { var o = {}; listRoadmaps(L).forEach(function (r) { o[r.id] = r; }); return o; }
  function rmChanges(b, a) { return Object.keys(a).map(function (k) { return { id: k, goal_title: a[k].goal_title, readiness_before: b[k] ? b[k].readiness : null, readiness_after: a[k].readiness, progress_before: b[k] ? b[k].progress : null, progress_after: a[k].progress }; }); }

  function submitQuiz(L, cid, answers) {
    var c = courseForLearner(L, cid); ensureStartable(c);
    var bl = levels(L), br = snapshot(L);
    if (c.progress.status === 'not_started') L.enrollments[cid] = { status: 'in_progress', lessons_done: [], started_at: now(), completed_at: null };
    var result = E.gradeQuiz(c.questions, answers, c.quiz.pass_threshold);
    var aid = S.seq++;
    L.attempts.push({ id: aid, course_id: cid, answers: answers, result: result, created_at: now() });
    E.assessmentEvidence(c, result).forEach(function (ev) { addEvidence(L, ev.competency, 'assessment', ev.level, ev.note, 'assessment_attempt:' + aid); });
    var done = completeIfDone(L, c);
    refreshAll(L); save();
    return { attempt_id: aid, changes: levelChanges(bl, levels(L)), roadmaps: rmChanges(br, snapshot(L)), completed: done };
  }
  function submitLab(L, cid, answers, interp) {
    var c = courseForLearner(L, cid);
    if (!c.progress.quiz_passed) throw new Error('Pass the course assessment before submitting the lab.');
    var bl = levels(L), br = snapshot(L);
    var result = E.checkLab(c.lab, answers, interp);
    var sid = S.seq++;
    L.labs.push({ id: sid, course_id: cid, answers: answers, interpretation: interp, result: result, created_at: now() });
    E.labEvidence(c.lab, result.passed).forEach(function (ev) { addEvidence(L, ev.competency, 'assessment', ev.level, ev.note, 'lab_submission:' + sid); });
    var done = completeIfDone(L, c);
    refreshAll(L); save();
    return { result: result, completed: done, changes: levelChanges(bl, levels(L)), roadmaps: rmChanges(br, snapshot(L)) };
  }

  // resume suggestions (keyword method from pathways/resume.py)
  var STRONG = /\b(advanced|expert|proficient|extensive|led|lead|designed|built|developed|\d+\+?\s*years?)\b/i;
  function resumeExtract(text) {
    if ((text || '').trim().length < 20) throw new Error('Resume text is too short to analyse.');
    var sentences = text.split(/(?<=[.!?])\s+|\n+/).map(function (s) { return s.trim(); }).filter(Boolean), out = [];
    D.competencies.forEach(function (c) {
      var best = null;
      (c.keywords || []).forEach(function (kw) {
        var re = new RegExp('(?<![a-z0-9])' + kw.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![a-z0-9])');
        sentences.forEach(function (s) {
          if (re.test(s.toLowerCase())) { var strong = STRONG.test(s); if (!best || (strong && !best[0])) best = [strong, kw, s]; }
        });
      });
      if (best) out.push({ competency: c.id, level: best[0] ? 45 : 30, note: 'Resume mentions “' + best[1] + '”: “' + best[2].slice(0, 160) + '”' });
    });
    return out;
  }

  // ------------------------------------------------------------------ helpers for views
  function fmtMin(m) { if (!m) return 'Not specified'; var h = Math.floor(m / 60), r = m % 60; return h && r ? h + ' h ' + r + ' min' : h ? h + ' h' : r + ' min'; }
  function titleCase(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }
  function bar(cur, target, reach, basis, thin, label) {
    return '<div class="bar' + (thin ? ' thin' : '') + '"><span class="fill ' + (basis || 'none') + '" style="width:' + Math.min(100, cur) + '%"></span>' +
      (reach != null && reach > cur ? '<span class="gapfill" style="left:' + cur + '%;width:' + (Math.min(100, reach) - cur) + '%"></span>' : '') +
      (target != null ? '<span class="target" style="left:' + target + '%"' + (label ? ' data-label="' + target + '"' : '') + '></span>' : '') + '</div>';
  }
  function ring(p, cls, color) { return '<div class="ring ' + (cls || '') + '" style="--p:' + p + (color ? ';--c:' + color : '') + '"><b>' + p + '%</b></div>'; }
  function chip(t, c) { return '<span class="chip ' + (c || '') + '">' + esc(t) + '</span>'; }
  function basisTag(b) { return '<span class="basis ' + b + '">' + esc(BASIS[b] || b) + '</span>'; }
  function banner(text, tag) { return '<div class="demo-banner" role="note"><span class="demo-tag">' + (tag || 'Demo') + '</span><span>' + text + '</span></div>'; }
  function groupBy(arr, k) { var o = [], m = {}; arr.forEach(function (x) { if (!m[x[k]]) { m[x[k]] = []; o.push([x[k], m[x[k]]]); } m[x[k]].push(x); }); return o; }
  function check() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 12.5l4.2 4.2L19 7"/></svg>'; }
  function lessonHtml(blocks) {
    var out = [], items = [];
    function inline(t) { return esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>'); }
    function flush() { if (items.length) { out.push('<ul>' + items.map(function (i) { return '<li>' + i + '</li>'; }).join('') + '</ul>'); items = []; } }
    blocks.forEach(function (b) {
      if (b && typeof b === 'object' && b.code) { flush(); out.push('<pre class="code"><code>' + esc(b.code.join('\n')) + '</code></pre>'); }
      else if (typeof b === 'string' && b.indexOf('- ') === 0) items.push(inline(b.slice(2)));
      else { flush(); out.push('<p>' + inline(String(b)) + '</p>'); }
    });
    flush(); return out.join('');
  }

  // ------------------------------------------------------------------ router
  var app = document.getElementById('app'), nav = document.getElementById('nav'), cleanup = null, flash = null;
  function parse(path) { var q = {}, parts = path.split('?'); (parts[1] || '').split('&').forEach(function (kv) { if (kv) { var p = kv.split('='); q[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || ''); } }); return { path: parts[0], q: q }; }
  function go(path, keepScroll) {
    if (cleanup) { cleanup(); cleanup = null; }
    document.body.className = '';
    var r = parse(path), p = r.path.split('/').filter(Boolean);
    if (!S.current || !S.users[S.current]) { renderNav(false); return viewLogin(); }
    renderNav(true, p[0]);
    try {
      if (!p.length || p[0] === 'dashboard') viewDashboard();
      else if (p[0] === 'competencies') viewCompetencies();
      else if (p[0] === 'goals' && p[1]) viewGoal(p[1], r.q);
      else if (p[0] === 'goals') viewGoals();
      else if (p[0] === 'roadmaps' && p[1]) viewRoadmap(p[1]);
      else if (p[0] === 'learn' && p[2] === 'assessment' && p[3]) viewResult(p[1], +p[3], r.q);
      else if (p[0] === 'learn' && p[2] === 'assessment') viewAssessment(p[1], r.q);
      else if (p[0] === 'learn' && p[2] === 'lab') viewLab(p[1], r.q);
      else if (p[0] === 'learn') viewCourse(p[1], r.q);
      else if (p[0] === 'compare') viewCompare(r.q);
      else viewDashboard();
    } catch (err) {
      app.innerHTML = '<div class="container-wide"><div class="form-error" style="margin-top:2rem">' + esc(err.message) + '</div><a class="btn btn-outline" href="/dashboard">Back to dashboard</a></div>';
    }
    if (!keepScroll) window.scrollTo(0, 0);
    S.path = path; save();
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href^="/"]');
    if (a && !e.ctrlKey && !e.metaKey) { e.preventDefault(); go(a.getAttribute('href')); }
  });

  function renderNav(show, section) {
    if (!show) { nav.hidden = true; return; }
    nav.hidden = false;
    var L = me(), links = [['dashboard', 'Dashboard'], ['competencies', 'My competencies'], ['goals', 'Goals & roadmaps'], ['compare', 'Compare demo learners']];
    nav.innerHTML = '<div class="nav-left"><a class="nav-brand" href="/dashboard">Antah.ai</a>' +
      '<button class="nav-toggle" id="navToggle" aria-label="Menu" aria-expanded="false"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button>' +
      '<div class="nav-links" id="navLinks">' + links.map(function (l) {
        var active = section === l[0] || (l[0] === 'goals' && section === 'roadmaps');
        return '<a href="/' + l[0] + '" class="' + (active ? 'active' : '') + '">' + l[1] + '</a>';
      }).join('') + '</div></div>' +
      '<div class="nav-right"><span class="demo-tag hide-sm">Browser demo</span><div class="avatar-wrap"><div class="avatar" id="avatarBtn" tabindex="0" title="' + esc(L.display_name) + '">' + esc(L.display_name[0].toUpperCase()) + '</div>' +
      '<div class="dropdown" id="dropdown"><div class="hi">' + esc(L.display_name) + '</div><a href="/dashboard">Dashboard</a><button class="linkish dd-btn" id="switchUser">Switch learner</button><button class="linkish dd-btn logout" id="resetAll">Reset all demo data</button></div></div></div>';
    var dd = document.getElementById('dropdown');
    document.getElementById('avatarBtn').onclick = function (e) { e.stopPropagation(); dd.classList.toggle('open'); };
    document.getElementById('navToggle').onclick = function (e) { e.stopPropagation(); document.getElementById('navLinks').classList.toggle('open'); };
    document.getElementById('switchUser').onclick = function () { S.current = null; save(); go('/'); };
    document.getElementById('resetAll').onclick = function () {
      if (this.dataset.armed) { initState(); save(); go('/'); PW.toast('All demo data reset.'); }
      else { this.dataset.armed = '1'; this.textContent = 'Click again to confirm reset'; }
    };
  }
  document.addEventListener('click', function () { var dd = document.getElementById('dropdown'); if (dd) dd.classList.remove('open'); });

  // ------------------------------------------------------------------ views
  function viewLogin() {
    var cards = D.demo_learners.map(function (d) {
      var L = S.users[d.username];
      return '<button class="pw-card login-pick" data-user="' + d.username + '"><div class="row" style="gap:.8rem"><div class="av-lg">' + esc(d.display_name[0]) + '</div><div style="text-align:left;min-width:0"><b>' + esc(d.display_name) + '</b>' +
        '<div class="xs muted">' + esc(d.education) + ' · ' + d.experience_years + ' yrs</div></div></div><div class="small muted" style="text-align:left;margin-top:.6rem">' +
        (d.username === 'demo_asha' ? 'Strong, assessment-validated Python; weaker statistics.' : 'New to Python and statistics.') +
        (L && Object.keys(L.roadmaps).length ? ' <b style="color:var(--done)">' + Object.keys(L.roadmaps).length + ' saved roadmap(s)</b>' : '') + '</div></button>';
    }).join('');
    var custom = Object.keys(S.users).filter(function (u) { return !S.users[u].is_demo; }).map(function (u) {
      return '<button class="chip brand login-own" data-user="' + esc(u) + '">' + esc(S.users[u].display_name) + '</button>';
    }).join(' ');
    app.innerHTML = '<div class="auth-wrap"><div class="auth-inner" style="max-width:560px"><div class="brand-big">Antah.ai</div>' +
      '<p class="auth-sub">Competency-based learning for India’s Official Statistical System (SIH26101). Pick a learner to explore goals, gaps, explainable recommendations and an interactive roadmap.</p>' +
      '<div class="grid-2" style="margin-top:1.5rem">' + cards + '</div>' +
      '<form class="pw-card" id="newForm" style="margin-top:1rem;text-align:left"><label for="newName">Or start as a new learner</label><div class="row" style="flex-wrap:nowrap"><input id="newName" maxlength="40" placeholder="Your name" required><button class="btn btn-primary" type="submit">Start</button></div>' +
      (custom ? '<div class="xs muted" style="margin-top:.6rem">Continue as: ' + custom + '</div>' : '') + '</form>' +
      banner('This is the browser edition of the AntahAI prototype. It uses the same recommendation engine as the Flask app, and your progress is kept only in this browser. ' + esc(D._meta.disclaimer)) + '</div></div>';
    app.querySelectorAll('[data-user]').forEach(function (b) { b.onclick = function () { S.current = b.dataset.user; save(); go('/dashboard'); }; });
    document.getElementById('newForm').onsubmit = function (e) {
      e.preventDefault(); var n = document.getElementById('newName').value.trim(); if (!n) return;
      var key = 'u_' + n.toLowerCase().replace(/[^a-z0-9]+/g, '_');
      if (!S.users[key]) S.users[key] = freshLearner(n);
      S.current = key; save(); go('/competencies');
    };
  }

  function viewDashboard() {
    var L = me(), rms = listRoadmaps(L), lv = levels(L), prog = progress(L);
    var hist = Object.keys(prog).map(function (cid) { return Object.assign({ course_id: cid, title: COURSE[cid].title }, prog[cid]); })
      .sort(function (a, b) { return (b.completed_at || b.started_at) > (a.completed_at || a.started_at) ? 1 : -1; });
    var validated = Object.keys(lv).filter(function (k) { return lv[k].basis === 'assessment'; }).length;
    var selfr = Object.keys(lv).filter(function (k) { return lv[k].basis === 'self_reported'; }).length;
    var nxt = rms.filter(function (r) { return r.next_action; })[0];
    var rows = D.competencies.map(function (c) { return Object.assign({ id: c.id, name: c.name, category: c.category }, lv[c.id] || { level: 0, basis: 'none' }); });
    app.innerHTML = '<div class="container-wide"><section class="hero"><div style="position:relative;z-index:1"><div class="eyebrow" style="color:#9CC8F2">Competency-based learning</div>' +
      '<h1>Welcome back, ' + esc(L.display_name) + '</h1><p>Your roadmaps share one competency profile. Complete a course once and it counts on every roadmap.</p>' +
      '<div class="hero-stats"><div><b>' + rms.length + '</b><span>Saved roadmaps</span></div><div><b>' + hist.filter(function (h) { return h.status === 'completed'; }).length + '</b><span>Courses completed</span></div>' +
      '<div><b>' + validated + '</b><span>Validated competencies</span></div><div><b>' + selfr + '</b><span>Self-reported</span></div></div></div>' +
      '<div style="position:relative;z-index:1" class="btn-row">' + (nxt ? '<a class="btn btn-primary" href="/learn/' + nxt.next_action.course_id + '?roadmap=' + nxt.id + '">' + esc(nxt.next_action.verb + ': ' + nxt.next_action.title) + '</a>' : '<a class="btn btn-primary" href="/goals">Choose a goal</a>') + '</div></section>' +
      banner(esc(D._meta.disclaimer)) +
      '<div class="grid-side pw-section"><div><div class="h2">My roadmaps <span class="count">' + rms.length + '</span></div><div class="grid-2">' +
      rms.map(function (r) {
        return '<article class="pw-card rm-card"><div class="top"><div class="goal-icon">' + (I[r.goal_icon] || I.flag) + '</div><div style="flex:1;min-width:0"><h3><a href="/roadmaps/' + r.id + '" style="color:inherit">' + esc(r.goal_title) + '</a></h3><div class="xs muted">' + esc(r.goal_tagline) + '</div></div>' + ring(r.readiness, 'sm') + '</div>' +
          '<div><div class="row between xs muted"><span>Courses completed</span><b style="color:var(--ink)">' + r.progress + '%</b></div><div class="progress ' + (r.progress === 100 ? 'done' : '') + '" style="margin-top:.3rem"><span style="width:' + r.progress + '%"></span></div></div>' +
          '<div class="next">' + (r.next_action ? '<span class="xs muted">Next step</span><br><b>' + esc(r.next_action.verb + ': ' + r.next_action.title) + '</b>' : r.readiness >= 100 ? '<b style="color:var(--done)">Goal requirements met</b>' : '<span class="small muted">No startable step. Open the roadmap to see what is locked or unavailable.</span>') + '</div>' +
          '<div class="btn-row"><a class="btn btn-brand btn-sm" href="/roadmaps/' + r.id + '">Open roadmap</a>' + (r.next_action ? '<a class="btn btn-soft btn-sm" href="/learn/' + r.next_action.course_id + '?roadmap=' + r.id + '">' + r.next_action.verb + '</a>' : '') + '<span class="xs muted" style="margin-left:auto">v' + r.version + '</span></div></article>';
      }).join('') +
      '<a class="pw-card rm-new" href="/goals"><div class="plus">+</div><b>' + (rms.length ? 'Create another roadmap' : 'Create your first roadmap') + '</b><span class="small">Pick a target role and see your gaps</span></a></div>' +
      '<div class="pw-section"><div class="h2">Learning history</div><div class="pw-card">' + (hist.length ? hist.map(function (h) {
        return '<div class="history-item"><span class="dot ' + h.status + '"></span><div style="flex:1;min-width:0"><a href="/learn/' + h.course_id + '"><b style="color:var(--ink)">' + esc(h.title) + '</b></a><div class="xs muted">' +
          (h.status === 'completed' ? 'Completed' : 'In progress · ' + h.percent + '%') + (h.best_score != null ? ' · best assessment ' + h.best_score + '%' : '') + (h.quiz_attempts ? ' · ' + h.quiz_attempts + ' attempt' + (h.quiz_attempts !== 1 ? 's' : '') : '') + '</div></div>' +
          chip(h.status === 'completed' ? 'Completed' : 'In progress', h.status === 'completed' ? 'ok' : 'brand') + '</div>';
      }).join('') : '<p class="small muted">Nothing started yet. Open a roadmap and choose <b>Start learning</b> on the recommended step.</p>') + '</div></div></div>' +
      '<aside><div class="h2">Competency profile</div><div class="pw-card"><div class="row between" style="margin-bottom:.8rem"><div class="row xs"><span class="basis assessment">Validated</span><span class="basis self_reported">Self</span><span class="basis none">None</span></div><a class="small" href="/competencies">Edit</a></div><div class="comp-list">' +
      groupBy(rows, 'category').map(function (g) {
        return '<div class="cat-title">' + esc(g[0]) + '</div>' + g[1].map(function (c) {
          return '<div class="comp-item"><div class="head"><span class="name">' + esc(c.name) + '</span><span class="lvl">' + c.level + '</span></div><div class="bar thin" title="' + BASIS[c.basis] + '"><span class="fill ' + c.basis + '" style="width:' + c.level + '%"></span></div></div>';
        }).join('');
      }).join('') + '</div><p class="xs muted" style="margin-top:1rem">Scale 0–100. Only passed assessments and labs create <b>validated</b> evidence; resume suggestions count only after you confirm them.</p></div></aside></div></div>';
  }

  function viewCompetencies() {
    var L = me(), lv = levels(L);
    var sugg = L.evidence.filter(function (e) { return e.source === 'resume_inferred' && !e.confirmed; });
    var rows = D.competencies.map(function (c) { return Object.assign({ id: c.id, name: c.name, category: c.category, description: c.description }, lv[c.id] || { level: 0, basis: 'none', self_reported: null, suggested: null, explanation: 'No evidence.' }); });
    app.innerHTML = '<div class="container-wide"><div class="pw-head"><div><div class="eyebrow">Step 1 · Competency profile</div><h1>What can you do today?</h1><p>Rate yourself honestly. Your rating is used as <b>self-reported</b> evidence until an assessment validates it. Resume suggestions only count after you confirm them.</p></div></div>' +
      '<div class="grid-side"><div><section class="pw-card"><div class="h2">About you</div><div class="grid-2">' +
      '<div class="field"><label for="f_name">Display name</label><input id="f_name" maxlength="80" value="' + esc(L.display_name) + '"></div>' +
      '<div class="field"><label for="f_org">Organisation / department</label><select id="f_org"><option value="">Not specified</option>' + D.organizations.map(function (o) { return '<option' + (o === L.profile.organization ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select><div class="hint">Department names only; no requirements are inferred from them.</div></div>' +
      '<div class="field"><label for="f_exp">Work experience (years)</label><input id="f_exp" type="number" min="0" max="60" value="' + (L.profile.experience_years == null ? '' : L.profile.experience_years) + '"></div>' +
      '<div class="field"><label for="f_edu">Education</label><input id="f_edu" maxlength="160" value="' + esc(L.profile.education) + '"></div></div>' +
      '<div class="field" style="margin-bottom:0"><label for="f_int">Learning interests</label><input id="f_int" maxlength="300" value="' + esc(L.profile.interests) + '" placeholder="e.g. survey methods, dashboards"></div></section>' +
      '<section class="pw-card pw-section"><div class="row between" style="margin-bottom:.5rem"><div class="h2" style="margin:0">Competencies</div><span class="xs muted">Self-rating on a 0–100 scale</span></div>' +
      '<div class="scale-guide" style="margin-bottom:.6rem"><div><b>0</b>No exposure</div><div><b>1–34</b>Beginner: needs guidance</div><div><b>35–64</b>Working: independent on routine tasks</div><div><b>65–100</b>Advanced: can teach or review others</div></div>' +
      groupBy(rows, 'category').map(function (g) {
        return '<div class="cat-title" style="margin-top:1.2rem">' + esc(g[0]) + '</div>' + g[1].map(function (c) {
          var ev = L.evidence.filter(function (e) { return e.competency === c.id; });
          var sr = c.self_reported == null ? 0 : c.self_reported;
          return '<div class="comp-edit" data-comp="' + c.id + '" data-initial="' + sr + '"><div><b>' + esc(c.name) + '</b>' + (c.suggested != null ? ' <span class="basis suggested">Resume: ' + c.suggested + '</span>' : '') + '<div class="desc">' + esc(c.description) + '</div></div>' +
            '<div class="slider"><input type="range" min="0" max="100" step="5" value="' + sr + '" aria-label="Self-rating for ' + esc(c.name) + '"><input type="number" min="0" max="100" value="' + sr + '" aria-label="Self-rating value for ' + esc(c.name) + '"></div>' +
            '<div class="eff"><b>' + c.level + '</b>' + basisTag(c.basis) + (ev.length ? '<div><button class="linkish xs" data-log>Evidence (' + ev.length + ')</button></div>' : '') + '</div>' +
            (ev.length ? '<div class="evidence-log"><div class="muted">' + esc(c.explanation) + '</div>' + ev.slice().reverse().map(function (e) {
              return '<div>' + basisTag(e.source) + ' <b>' + e.level + '</b> · ' + e.created_at.slice(0, 10) + (e.source === 'resume_inferred' ? ' · ' + (e.confirmed ? 'confirmed' : 'awaiting confirmation') : '') + '<br><span class="muted">' + esc(e.note) + '</span></div>';
            }).join('') + '</div>' : '') + '</div>';
        }).join('');
      }).join('') + '</section><div class="sticky-save"><span class="small muted" id="dirtyNote">Changes update every saved roadmap automatically.</span><button class="btn btn-primary" id="saveBtn">Save profile</button></div></div>' +
      '<aside><section class="pw-card"><div class="h2">Resume assist ' + chip('optional', 'warn') + '</div><p class="small muted">Paste your resume text or open a .txt file. It is analysed only in this browser. Suggestions are capped at 45, and nothing counts until you confirm it.</p>' +
      '<label class="dropzone" for="resumeFile" style="margin-top:.8rem"><input type="file" id="resumeFile" accept=".txt,text/plain" hidden><span id="dropText">Open a .txt resume</span></label>' +
      '<div class="field" style="margin-top:.7rem"><label for="resumeText" class="small">…or paste text</label><textarea id="resumeText" rows="5" placeholder="e.g. Built pandas pipelines for PLFS survey data over 4 years. Wrote SQL joins across district tables. Created Tableau dashboards."></textarea></div>' +
      '<button class="btn btn-soft btn-sm" id="extractBtn" style="width:100%">Suggest competencies</button><div id="resumeError" class="form-error" hidden style="margin-top:.7rem"></div>' +
      '<div id="suggBox" style="margin-top:1rem"' + (sugg.length ? '' : ' hidden') + '><div class="mini-title">Suggestions to confirm</div>' + sugg.map(function (s) {
        return '<div class="sugg" data-id="' + s.id + '"><div><b class="small">' + esc(COMPS[s.competency].name) + '</b><div class="xs muted">' + esc(s.note) + '</div></div><input type="number" min="0" max="100" value="' + s.level + '" aria-label="Level to confirm"><div class="row" style="gap:.3rem"><button class="btn btn-brand btn-sm" data-accept>Confirm</button><button class="btn btn-ghost btn-sm" data-reject>Reject</button></div></div>';
      }).join('') + '</div></section>' +
      '<section class="pw-card pw-section"><div class="h2" style="font-size:1rem">How levels change</div><ul class="reasons"><li><b>Self-rating</b> is used until you have assessment evidence.</li><li><b>Passing an assessment</b> (≥70%) records validated evidence. Its level scales with how many questions you answered correctly for that competency.</li><li><b>Opening a course or reading lessons</b> never raises a level.</li><li>If a validated level is lower than your self-rating, the <b>validated level wins</b>.</li></ul></section></aside></div></div>';
    app.querySelectorAll('.comp-edit').forEach(function (row) {
      var r = row.querySelector('input[type=range]'), n = row.querySelector('input[type=number]');
      r.oninput = function () { n.value = r.value; document.getElementById('dirtyNote').textContent = 'Unsaved changes'; };
      n.oninput = function () { r.value = Math.max(0, Math.min(100, +n.value || 0)); document.getElementById('dirtyNote').textContent = 'Unsaved changes'; };
      var t = row.querySelector('[data-log]'); if (t) t.onclick = function () { row.querySelector('.evidence-log').classList.toggle('open'); };
    });
    document.getElementById('saveBtn').onclick = function () {
      var exp = document.getElementById('f_exp').value;
      if (exp !== '' && (!/^\d+$/.test(exp) || +exp > 60)) return PW.toast('Experience must be a whole number between 0 and 60.', true);
      var changed = 0;
      app.querySelectorAll('.comp-edit').forEach(function (row) {
        var v = Math.max(0, Math.min(100, +row.querySelector('input[type=number]').value || 0));
        if (v !== +row.dataset.initial) { addEvidence(L, row.dataset.comp, 'self_reported', v, 'Self-reported rating.'); changed++; }
      });
      L.display_name = document.getElementById('f_name').value.trim() || L.display_name;
      L.profile = { organization: document.getElementById('f_org').value, experience_years: exp === '' ? null : +exp, education: document.getElementById('f_edu').value, interests: document.getElementById('f_int').value };
      refreshAll(L); save(); go('/competencies'); PW.toast('Profile saved. Your roadmaps were recalculated.');
    };
    document.getElementById('resumeFile').onchange = function () {
      var f = this.files[0]; if (!f) return;
      if (f.size > 2 * 1024 * 1024) return PW.toast('Resume file is larger than 2 MB.', true);
      var rd = new FileReader(); rd.onload = function () { document.getElementById('resumeText').value = String(rd.result).slice(0, 40000); document.getElementById('dropText').textContent = f.name; }; rd.readAsText(f);
    };
    document.getElementById('extractBtn').onclick = function () {
      var box = document.getElementById('resumeError'); box.hidden = true;
      try {
        var found = resumeExtract(document.getElementById('resumeText').value);
        L.evidence = L.evidence.filter(function (e) { return !(e.source === 'resume_inferred' && !e.confirmed); });
        found.forEach(function (s) { addEvidence(L, s.competency, 'resume_inferred', s.level, s.note, 'keyword'); });
        save(); go('/competencies', true);
        PW.toast(found.length ? found.length + ' suggestion(s) found. Please confirm or reject each.' : 'No competencies recognised in that text.');
      } catch (err) { box.textContent = err.message; box.hidden = false; }
    };
    var sl = document.getElementById('suggBox');
    sl.onclick = function (e) {
      var b = e.target.closest('[data-accept],[data-reject]'); if (!b) return;
      var row = b.closest('.sugg'), id = +row.dataset.id, ev = L.evidence.filter(function (x) { return x.id === id; })[0];
      if (!ev) return;
      if (b.hasAttribute('data-reject')) L.evidence = L.evidence.filter(function (x) { return x.id !== id; });
      else {
        var lvl = Math.max(0, Math.min(100, +row.querySelector('input').value || 0));
        ev.confirmed = 1; addEvidence(L, ev.competency, 'self_reported', lvl, 'Confirmed by learner from resume suggestion (' + ev.note + ')', 'resume_evidence:' + id);
        refreshAll(L);
      }
      save(); go('/competencies', true); PW.toast(b.hasAttribute('data-reject') ? 'Suggestion rejected.' : 'Confirmed and saved as self-reported evidence.');
    };
  }

  function viewGoals() {
    var L = me(), lv = levels(L);
    app.innerHTML = '<div class="container-wide"><div class="pw-head"><div><div class="eyebrow">Step 2 · Choose a target</div><h1>Where do you want to grow?</h1><p>Each goal lists the competencies it requires and the level expected. Readiness is calculated from your current evidence.</p></div><a class="btn btn-soft btn-sm" href="/competencies">Review my competencies first</a></div><div class="grid-2">' +
      D.goals.map(function (g) {
        var gaps = E.computeGaps(g, lv, COMPS), rd = E.goalReadiness(gaps), saved = L.roadmaps[g.id], open = gaps.filter(function (x) { return !x.met; }).length;
        return '<article class="pw-card goal-card"><div class="row" style="gap:.9rem;align-items:flex-start"><div class="goal-icon">' + (I[g.icon] || I.flag) + '</div><div style="flex:1;min-width:0"><h3>' + esc(g.title) + '</h3><div class="small muted">' + esc(g.tagline) + '</div></div>' + ring(rd, 'sm') + '</div>' +
          '<div><div class="mini-title">Required competencies</div>' + gaps.map(function (x) {
            return '<div class="dev-row" style="margin-bottom:.7rem"><span class="small">' + esc(x.name) + (x.weight === 3 ? ' <span class="chip brand" style="font-size:.65rem">core</span>' : '') + '</span><span class="xs' + (x.met ? '" style="color:var(--done);font-weight:700"' : ' muted"') + '>' + x.current + ' / ' + x.target + '</span>' + bar(x.current, x.target, x.met ? null : x.target, x.basis, true) + '</div>';
          }).join('') + '</div><div class="foot">' + (saved
            ? chip('Roadmap saved · ' + saved.graph.summary.progress + '% done', 'ok') + '<div class="btn-row"><a class="btn btn-soft btn-sm" href="/goals/' + g.id + '">Gaps</a><a class="btn btn-brand btn-sm" href="/roadmaps/' + g.id + '">Open roadmap</a></div>'
            : '<span class="xs muted">' + open + ' gap' + (open !== 1 ? 's' : '') + ' to close</span><a class="btn btn-primary btn-sm" href="/goals/' + g.id + '">View gaps &amp; recommendations</a>') + '</div></article>';
      }).join('') + '</div>' + banner('Goal requirements are illustrative prototype mappings aligned to the MoSPI/DIID problem statement. They are not official job-role competency frameworks and need validation.', 'Prototype') + '</div>';
  }

  var SCORE = [['gap_coverage', 'Gap coverage'], ['goal_relevance', 'Goal relevance'], ['prereq_readiness', 'Prerequisite readiness'], ['level_fit', 'Level fit']];
  function scoreRows(sc) {
    return SCORE.map(function (s) { var v = Math.round(sc.components[s[0]] * 100); return '<div class="score-row"><span>' + s[1] + ' <span class="muted xs">×' + Math.round(sc.weights[s[0]] * 100) + '%</span></span><div class="bar"><span class="fill" style="width:' + v + '%"></span></div><b>' + v + '</b></div>'; }).join('');
  }
  function viewGoal(gid, q) {
    var L = me(), g = GOALS[gid]; if (!g) throw new Error('Unknown goal.');
    var lv = levels(L), rev = q.revision === '1';
    var a = E.buildRecommendations(g, COURSES, lv, progress(L), COMPS, null, rev);
    var saved = !!L.roadmaps[gid];
    var ST = { ready: ['Ready to start', 'brand'], locked: ['Locked', 'lock'], unavailable: ['Unavailable', 'bad'] };
    var KIND = { prereq_met: 'Skipped', already_met: 'Already met', completed: 'Completed', redundant: 'Not needed' };
    app.innerHTML = '<div class="container-wide"><div class="pw-head"><div><div class="eyebrow"><a href="/goals">Goals</a> / Gap analysis</div><h1>' + esc(g.title) + '</h1><p>' + esc(g.description) + '</p></div><div class="row" style="gap:1rem">' + ring(a.readiness, 'lg') + '<div class="small muted" style="max-width:160px">Weighted readiness from your current evidence</div></div></div>' +
      '<div class="grid-side"><div><section class="pw-card"><div class="h2" style="margin-bottom:.4rem">1 · Competency requirements and your gaps</div><p class="small muted" style="margin-bottom:1rem">Targets use a 0–100 scale. The striped segment is the gap. Missing evidence is treated as 0 and flagged.</p>' +
      '<div class="table-scroll"><table class="gap-table"><thead><tr><th>Competency</th><th class="hide-sm">Evidence</th><th>You → target</th><th></th></tr></thead><tbody>' + a.gaps.map(function (x) {
        return '<tr><td><b>' + esc(x.name) + '</b><div class="xs muted">Priority ' + '●'.repeat(x.weight) + '○'.repeat(3 - x.weight) + '</div></td><td class="hide-sm">' + basisTag(x.basis) + '</td><td class="num">' + x.current + ' → ' + x.target + (x.met ? ' ' + chip('met', 'ok') : ' <span class="xs muted">(gap ' + x.gap + ')</span>') + '</td><td class="barcell">' + bar(x.current, x.target, x.met ? null : x.target, x.basis, false, true) + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      (g.entry_prerequisites || []).map(function (p) { return '<div class="notice" style="margin-top:1rem">Entry expectation: <b>' + esc(COMPS[p.competency].name) + ' ≥ ' + p.min_level + '</b> (you: ' + E.levelOf(lv, p.competency) + '). ' + esc(p.note || '') + '</div>'; }).join('') +
      (a.uncovered.length ? '<div class="form-error" style="margin-top:1rem">No available course closes: ' + esc(a.uncovered.map(function (u) { return u.name; }).join(', ')) + '. It stays on the roadmap as an <b>unavailable</b> step so the gap is not hidden.</div>' : '') + '</section>' +
      '<section class="pw-section"><div class="h2">2 · Recommended courses <span class="count">' + a.recommendations.length + '</span></div><p class="small muted" style="margin:-.4rem 0 1rem">A small set chosen to close your weighted gap. Courses you can start now come first. A locked course never outranks one you can start, whatever its score.</p>' +
      (a.recommendations.length ? a.recommendations.map(function (r) {
        var st = ST[r.status];
        return '<article class="pw-card rec-card ' + r.status + '" style="margin-bottom:1rem"><div class="row" style="align-items:flex-start;gap:.8rem"><div class="rec-rank">' + r.rank + '</div><div style="flex:1;min-width:0"><div class="row between" style="align-items:flex-start"><h3>' + esc(r.title) + '</h3><div class="row" style="gap:.35rem">' + chip(st[0], st[1]) + (r.role === 'prerequisite' ? chip('Foundation', 'warn') : '') + chip(titleCase(r.difficulty)) + '</div></div>' +
          '<p class="small muted" style="margin-top:.2rem">' + esc(r.summary) + '</p><ul class="reasons">' + r.reasons.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div></div>' +
          '<div class="rec-grid"><div><div class="mini-title">Competencies developed</div>' + r.develops.map(function (d) {
            return '<div class="dev-row"><span>' + esc(d.name) + '</span><span class="xs muted">now ' + d.current + ' → up to ' + d.course_reaches + (d.target != null ? ' · goal ' + d.target : ' · not in goal') + '</span>' + bar(d.current, d.target, d.course_reaches, d.basis, true) + '</div>';
          }).join('') + '<div class="mini-title" style="margin-top:.8rem">Learning outcomes</div><ul class="small" style="margin-left:1.1rem;color:var(--ink-2)">' + r.outcomes.map(function (o) { return '<li>' + esc(o) + '</li>'; }).join('') + '</ul></div>' +
          '<div><div class="mini-title">Score breakdown · ' + Math.round(r.score.total * 100) + '/100</div>' + scoreRows(r.score) +
          '<div class="mini-title" style="margin-top:.8rem">Prerequisites</div>' + (r.prerequisites.length ? r.prerequisites.map(function (p) { return '<div class="prq"><span class="' + (p.satisfied ? 'ok' : 'no') + '">' + (p.satisfied ? '✓' : '✗') + '</span>' + esc(p.name) + ' ≥ ' + p.min_level + ' <span class="xs muted">(you: ' + p.current + ')</span></div>'; }).join('') : '<div class="small muted">None</div>') +
          '<div class="row small" style="margin-top:.8rem;gap:1rem"><span><span class="mini-title" style="display:inline">Duration</span> ' + fmtMin(r.duration_minutes) + '</span><span><span class="mini-title" style="display:inline">Availability</span> ' + (r.availability === 'available' ? 'Available' : '<b style="color:var(--unav)">Unavailable</b>') + '</span></div>' +
          '<div class="xs muted" style="margin-top:.3rem">Source: ' + (r.source === 'local' ? 'Curated local catalogue (demo content)' : 'iGOT connector: MOCK, not a live listing') + '</div></div></div></article>';
      }).join('') : '<div class="pw-card"><b>No courses needed.</b> <span class="muted">Your current evidence meets every target for this goal.</span></div>') +
      (a.skipped.length ? '<div class="pw-card flat" style="margin-top:1rem"><div class="h2" style="font-size:1rem">Why not these courses?</div>' + a.skipped.map(function (s) {
        return '<div class="skip-item">' + chip(KIND[s.kind], s.kind === 'redundant' ? '' : 'ok') + '<div><b>' + esc(s.title) + '</b><div class="muted">' + esc(s.reason) + '</div></div></div>';
      }).join('') + (!rev ? '<p class="xs muted" style="margin-top:.6rem">Want to revise completed courses? <a href="/goals/' + gid + '?revision=1">Include completed courses</a></p>' : '') + '</div>' : '') + '</section></div>' +
      '<aside class="sticky-aside"><div class="pw-card"><div class="h2" style="font-size:1rem">3 · Generate your roadmap</div><p class="small muted">The roadmap orders these courses by prerequisites. It shows where you can work in parallel, and it updates automatically as you learn.</p>' +
      '<div class="confirm-box" style="margin-top:.9rem"><input type="checkbox" id="confirmReq"' + (saved ? ' checked' : '') + '><label for="confirmReq">I have reviewed the ' + a.gaps.length + ' competency requirements and target levels for <b>' + esc(g.title) + '</b>.</label></div>' +
      '<button class="btn btn-primary" id="genBtn" style="width:100%;margin-top:.9rem"' + (saved ? '' : ' disabled') + '>' + (saved ? 'Update &amp; open roadmap' : 'Generate &amp; save roadmap') + '</button><hr class="divider"><div class="mini-title">Scoring weights (configurable)</div>' +
      SCORE.map(function (s) { return '<div class="row between small"><span>' + s[1] + '</span><b>' + Math.round(a.weights[s[0]] * 100) + '%</b></div>'; }).join('') +
      '<p class="xs muted" style="margin-top:.5rem">These are starting weights, not calibrated accuracy claims. Prerequisites and completion are hard rules applied before scoring.</p></div></aside></div></div>';
    var cb = document.getElementById('confirmReq'), btn = document.getElementById('genBtn');
    cb.onchange = function () { btn.disabled = !cb.checked; };
    btn.onclick = function () { generateRoadmap(L, gid); save(); go('/roadmaps/' + gid); };
  }

  function viewRoadmap(gid) {
    var L = me(), rmRec = L.roadmaps[gid];
    if (!rmRec) { app.innerHTML = '<div class="container-wide"><div class="pw-card" style="margin-top:2rem"><h3>No saved roadmap for this goal yet.</h3><p class="muted">Review the requirements and generate one first.</p><a class="btn btn-primary" style="margin-top:.8rem" href="/goals/' + gid + '">Go to the goal</a></div></div>'; return; }
    document.body.className = 'roadmap-page';
    var all = listRoadmaps(L);
    app.innerHTML = '<div class="rm-shell"><div class="rm-bar"><div class="title"><div class="ring sm" id="rmRing"><b id="rmReadiness"></b></div><div style="min-width:0"><div class="meta">Learning roadmap · <span class="demo-tag">Demo data</span></div><h1>' + esc(GOALS[gid].title) + '</h1></div></div>' +
      '<div class="stats"><div class="stat-mini hide-sm">Courses done<b id="rmDone"></b></div><div class="stat-mini hide-sm">Updated<b id="rmUpdated"></b></div>' +
      (all.length > 1 ? '<select id="rmSwitch" aria-label="Switch roadmap">' + all.map(function (r) { return '<option value="' + r.id + '"' + (r.id === gid ? ' selected' : '') + '>' + esc(r.goal_title) + '</option>'; }).join('') + '</select>' : '') +
      '<span id="rmNext"></span><button class="btn btn-soft btn-sm" id="rmRegen">Recalculate</button></div></div>' +
      '<div class="rm-stage"><div class="rm-canvas" id="rmCanvas" aria-label="Interactive learning roadmap. Drag to pan, scroll or pinch to zoom, press Enter on a step for details."></div>' +
      '<div class="rm-legend" id="rmLegend"><div class="items" role="list" aria-label="Legend"><b>Legend</b>' +
      [['completed', 'Completed'], ['in_progress', 'In progress'], ['available', 'Available'], ['recommended', 'Recommended next'], ['locked', 'Locked (prerequisite unmet)'], ['unavailable', 'Unavailable resource'], ['milestone', 'Skill milestone'], ['edge-done', 'Travelled'], ['edge-next', 'Next step']]
        .map(function (x) { return '<span class="lg" role="listitem"><i class="' + x[0] + '"></i>' + x[1] + '</span>'; }).join('') +
      '<button class="toggle" id="legendToggle" aria-expanded="true">Hide</button></div></div><div class="rm-controls" id="rmControls"></div><div class="rm-zoom" id="rmZoom">100%</div><div class="rm-minimap" id="rmMini" aria-label="Minimap. Click to move the view."></div></div></div>' +
      '<aside class="drawer" id="drawer" aria-hidden="true" role="dialog" aria-labelledby="drawerTitle"><div class="drawer-head"><div id="drawerTitle" style="min-width:0"></div><button class="drawer-close" id="drawerClose" aria-label="Close details">' + I.close + '</button></div><div class="drawer-body" id="drawerBody"></div><div class="drawer-foot" id="drawerFoot"></div></aside>';
    var canvas = document.getElementById('rmCanvas'), drawerEl = document.getElementById('drawer'), data = null;
    var map = new PWRoadmap.Roadmap(canvas, { minimap: document.getElementById('rmMini'), onZoom: function (k) { document.getElementById('rmZoom').textContent = Math.round(k * 100) + '%'; }, onSelect: openDrawer, onClear: closeDrawer });
    var ctl = document.getElementById('rmControls');
    [['plus', 'Zoom in', function () { map.zoomBy(1.25, null, null, true); }], ['minus', 'Zoom out', function () { map.zoomBy(0.8, null, null, true); }],
     ['fit', 'Fit to view', function () { map.fit(true); }], ['reset', 'Reset to start (100%)', function () { map.reset(); }]].forEach(function (b) {
      var btn = document.createElement('button'); btn.innerHTML = I[b[0]]; btn.title = b[1]; btn.setAttribute('aria-label', b[1]); btn.onclick = b[2]; ctl.appendChild(btn);
    });
    var lg = document.getElementById('legendToggle');
    lg.onclick = function () { var c = document.getElementById('rmLegend').classList.toggle('collapsed'); lg.textContent = c ? 'Show' : 'Hide'; };
    if (window.innerWidth < 760) { document.getElementById('rmLegend').classList.add('collapsed'); lg.textContent = 'Show'; }
    document.getElementById('drawerClose').onclick = function () { map.clearSelection(true); };
    var sw = document.getElementById('rmSwitch'); if (sw) sw.onchange = function () { go('/roadmaps/' + sw.value); };
    function onKey(e) {
      if (e.target.matches && e.target.matches('input,select,textarea')) return;
      if (e.key === 'Escape') map.clearSelection(true);
      if (e.key === '+' || e.key === '=') map.zoomBy(1.2, null, null, true);
      if (e.key === '-') map.zoomBy(0.83, null, null, true);
      if (e.key === '0') map.fit(true);
    }
    document.addEventListener('keydown', onKey);
    cleanup = function () { document.removeEventListener('keydown', onKey); };
    function paint() {
      var rec = L.roadmaps[gid], g = rec.graph;
      data = { nodes: g.nodes, edges: g.edges, width: g.size.width, height: g.size.height, analysis: g.analysis };
      var courses = g.nodes.filter(function (n) { return n.type === 'course'; }), done = courses.filter(function (n) { return n.state === 'completed'; }).length;
      document.getElementById('rmDone').textContent = done + ' / ' + courses.length;
      document.getElementById('rmReadiness').textContent = g.summary.readiness + '%';
      document.getElementById('rmRing').style.setProperty('--p', g.summary.readiness);
      document.getElementById('rmUpdated').textContent = 'v' + rec.version;
      var na = g.summary.next_action;
      document.getElementById('rmNext').innerHTML = na ? '<button class="btn btn-primary btn-sm" id="rmNextBtn">' + esc(na.verb + ': ' + na.title) + '</button>' : '';
      if (na) document.getElementById('rmNextBtn').onclick = function () { var id = 'course:' + na.course_id; map.select(id); map.centerOn(id, Math.max(map.t.k, 0.9), true); };
      map.render(data);
    }
    function openDrawer(node) {
      var parts = PWRoadmap.drawer(node, { roadmapId: gid, data: data, nodes: map.nodes, analysis: data.analysis, goalUrl: '/goals/' + gid });
      document.getElementById('drawerTitle').innerHTML = parts.head;
      document.getElementById('drawerBody').innerHTML = parts.body;
      var foot = document.getElementById('drawerFoot'); foot.innerHTML = parts.foot; foot.hidden = !parts.foot;
      drawerEl.classList.add('open'); drawerEl.setAttribute('aria-hidden', 'false'); map.drawerOpen = true;
      var r = canvas.getBoundingClientRect(), el = map.els[node.id].getBoundingClientRect();
      var vr = r.width > 760 ? r.right - 440 : r.right, vb = r.width > 760 ? r.bottom : r.top + r.height * 0.22;
      if (el.right > vr - 20 || el.left < r.left || el.bottom > vb || el.top < r.top) map.centerOn(node.id, null, true);
      var st = foot.querySelector('[data-start]');
      if (st) st.onclick = function () { try { startCourse(L, st.getAttribute('data-start')); go('/learn/' + st.getAttribute('data-start') + '?roadmap=' + gid); } catch (err) { PW.toast(err.message, true); } };
      var pre = foot.querySelector('[data-prereqs]');
      if (pre) pre.onclick = function () { map.highlightPath(pre.getAttribute('data-prereqs')); PW.toast('Highlighted the steps that lead to this course.'); };
    }
    function closeDrawer() { drawerEl.classList.remove('open'); drawerEl.setAttribute('aria-hidden', 'true'); map.drawerOpen = false; }
    document.getElementById('rmRegen').onclick = function () { generateRoadmap(L, gid); save(); closeDrawer(); paint(); PW.toast('Roadmap recalculated from your latest evidence.'); };
    requestAnimationFrame(paint);
  }

  function viewCourse(cid, q) {
    var L = me(), c = courseForLearner(L, cid); if (!c) throw new Error('Unknown course.');
    var rid = q.roadmap, rq = rid ? '?roadmap=' + rid : '', pr = c.progress, done = pr.lessons_done || [];
    var back = rid ? '<a href="/roadmaps/' + rid + '">← Back to roadmap</a>' : '<a href="/dashboard">← Dashboard</a>';
    var head = '<div class="pw-head" style="padding-bottom:0"><div><div class="eyebrow">' + back + '</div><h1>' + esc(c.title) + '</h1><div class="row" style="margin-top:.5rem">' + chip(titleCase(c.difficulty)) + chip(c.duration_verified ? fmtMin(c.duration_minutes) : 'Duration not verified') +
      chip(c.source === 'local' ? 'Curated · demonstration content' : 'iGOT connector · MOCK', c.source === 'local' ? 'brand' : 'bad') + (pr.status === 'completed' ? chip('Completed', 'ok') : pr.status === 'in_progress' ? chip('In progress · ' + pr.percent + '%', 'brand') : '') + '</div></div></div>';
    if (c.availability !== 'available') { app.innerHTML = '<div class="container-wide">' + head + '<div class="pw-card" style="margin-top:1.5rem"><h3>Content unavailable</h3><p class="muted" style="margin-top:.4rem">This listing comes from the <b>mock iGOT connector</b>. There is no live iGOT connection in this prototype, so no content, duration or availability can be confirmed. It stays on roadmaps so the gap it would close is visible.</p></div></div>'; return; }
    var lesson = c.lessons.filter(function (l) { return l.id === q.lesson; })[0] || c.lessons.filter(function (l) { return done.indexOf(l.id) < 0; })[0] || c.lessons[0];
    var locked = c.locked && pr.status === 'not_started';
    var lessonLink = function (lid) { return '/learn/' + cid + '?lesson=' + lid + (rid ? '&roadmap=' + rid : ''); };
    app.innerHTML = '<div class="container-wide">' + head + '<div class="player"><aside class="player-side pw-card" style="padding:1rem"><div class="mini-title" style="padding:0 .5rem">Your progress</div><div class="progress ' + (pr.status === 'completed' ? 'done' : '') + '" style="margin:0 .5rem .8rem"><span style="width:' + (pr.percent || 0) + '%"></span></div>' +
      c.lessons.map(function (l, i) { return '<a class="step ' + (l.id === lesson.id ? 'current' : '') + '" href="' + lessonLink(l.id) + '"><span class="step-ico ' + (done.indexOf(l.id) >= 0 ? 'done' : '') + '">' + (done.indexOf(l.id) >= 0 ? check() : '<span class="xs">' + (i + 1) + '</span>') + '</span><span>' + esc(l.title) + '<br><span class="xs muted">' + l.minutes + ' min</span></span></a>'; }).join('') +
      '<hr class="divider" style="margin:.6rem 0"><a class="step ' + (locked ? 'disabled' : '') + '" href="/learn/' + cid + '/assessment' + rq + '"><span class="step-ico ' + (pr.quiz_passed ? 'done' : '') + '">' + (pr.quiz_passed ? check() : '?') + '</span><span>Assessment<br><span class="xs muted">' + (pr.best_score != null ? 'Best ' + pr.best_score + '% · ' : '') + 'pass 70%</span></span></a>' +
      (c.lab ? '<a class="step ' + (pr.quiz_passed ? '' : 'disabled') + '" href="/learn/' + cid + '/lab' + rq + '"><span class="step-ico ' + (pr.lab_passed ? 'done' : '') + '">' + (pr.lab_passed ? check() : 'L') + '</span><span>Practical lab<br><span class="xs muted">' + (pr.quiz_passed ? esc(c.lab.title) : 'Unlocks after assessment') + '</span></span></a>' : '') +
      '<hr class="divider" style="margin:.6rem 0"><div class="mini-title" style="padding:0 .5rem">Develops</div>' + c.develops_named.map(function (d) { return '<div class="dev-row" style="padding:0 .5rem"><span class="small">' + esc(d.name) + '</span><span class="xs muted">' + d.current + ' → up to ' + d.reaches + '</span>' + bar(d.current, null, d.reaches, d.basis, true) + '</div>'; }).join('') + '</aside>' +
      '<section>' + (locked ? '<div class="form-error"><b>Locked.</b> You can preview the lessons, but you need ' + c.prereq_status.filter(function (p) { return !p.satisfied; }).map(function (p) { return '<b>' + esc(p.name) + ' ≥ ' + p.min_level + '</b> (you: ' + p.current + ')'; }).join(', ') + ' before starting or taking the assessment.</div>' : '') +
      '<article class="pw-card lesson" style="padding:1.75rem 2rem"><div class="eyebrow">Lesson ' + (c.lessons.indexOf(lesson) + 1) + ' of ' + c.lessons.length + ' · ' + lesson.minutes + ' min</div><h2>' + esc(lesson.title) + '</h2>' + lessonHtml(lesson.body) +
      '<hr class="divider"><div class="row between"><span class="xs muted">Marking a lesson as read updates your progress only. Competency levels change only when you pass the assessment.</span>' + (locked ? '' : '<button class="btn btn-primary" id="markBtn">' + (done.indexOf(lesson.id) >= 0 ? 'Next lesson →' : 'Mark as read &amp; continue →') + '</button>') + '</div></article>' +
      '<p class="xs muted" style="margin-top:.8rem">Demonstration learning content written for the AntahAI prototype. It is not an official iGOT course.</p></section></div></div>';
    var mb = document.getElementById('markBtn');
    if (mb) mb.onclick = function () {
      try {
        markLesson(L, cid, lesson.id);
        var idx = c.lessons.indexOf(lesson);
        go(idx + 1 < c.lessons.length ? lessonLink(c.lessons[idx + 1].id) : '/learn/' + cid + '/assessment' + rq);
      } catch (err) { PW.toast(err.message, true); }
    };
  }

  function viewAssessment(cid, q) {
    var L = me(), c = courseForLearner(L, cid); if (!c) throw new Error('Unknown course.');
    var rid = q.roadmap, rq = rid ? '?roadmap=' + rid : '', err = null;
    if (c.availability !== 'available') err = 'This course is not available, so it has no assessment.';
    else if (c.locked && c.progress.status === 'not_started') err = 'Prerequisites are not met yet.';
    var head = '<div class="pw-head"><div><div class="eyebrow"><a href="/learn/' + cid + rq + '">← ' + esc(c.title) + '</a></div><h1>Assessment</h1><p>' + c.questions.length + ' questions · pass mark ' + Math.round((c.quiz ? c.quiz.pass_threshold : 0.7) * 100) + '%. Each question is mapped to a competency. If you score below the pass mark, you get targeted revision and can retry.</p></div></div>';
    if (err) { app.innerHTML = '<div class="container">' + head + '<div class="form-error">' + esc(err) + '</div><a class="btn btn-outline" href="/learn/' + cid + rq + '">Back to course</a></div>'; return; }
    app.innerHTML = '<div class="container">' + head + '<form id="quizForm">' + c.questions.map(function (qq, i) {
      return '<fieldset class="q"><legend><span class="qn">Q' + (i + 1) + '.</span>' + esc(qq.text) + '</legend>' + qq.options.map(function (o, j) { return '<label class="opt"><input type="radio" name="q_' + qq.id + '" value="' + j + '"> <span>' + esc(o) + '</span></label>'; }).join('') + '</fieldset>';
    }).join('') + '<div class="row between" style="margin:1.25rem 0 3rem"><span class="small muted" id="answered">0 of ' + c.questions.length + ' answered</span><button class="btn btn-primary" type="submit">Submit answers</button></div></form></div>';
    var f = document.getElementById('quizForm'), total = c.questions.length;
    f.onchange = function () { document.getElementById('answered').textContent = f.querySelectorAll('input:checked').length + ' of ' + total + ' answered'; };
    f.onsubmit = function (e) {
      e.preventDefault();
      var n = f.querySelectorAll('input:checked').length;
      if (n < total && !f.dataset.confirmed) { f.dataset.confirmed = '1'; return PW.toast((total - n) + ' question(s) unanswered. They count as incorrect. Submit again to confirm.'); }
      var ans = {}; c.questions.forEach(function (qq) { var el = f.querySelector('input[name="q_' + qq.id + '"]:checked'); ans[qq.id] = el ? +el.value : null; });
      try { flash = submitQuiz(L, cid, ans); go('/learn/' + cid + '/assessment/' + flash.attempt_id + rq); } catch (x) { PW.toast(x.message, true); }
    };
  }

  function viewResult(cid, aid, q) {
    var L = me(), c = courseForLearner(L, cid), at = L.attempts.filter(function (a) { return a.id === aid; })[0];
    if (!at) throw new Error('Attempt not found.');
    var r = at.result, rid = q.roadmap, rq = rid ? '?roadmap=' + rid : '';
    var fresh = flash && flash.attempt_id === aid ? flash : {};
    var ids = L.attempts.filter(function (a) { return a.course_id === cid; }).map(function (a) { return a.id; });
    var ev = L.evidence.filter(function (e) { return e.origin === 'assessment_attempt:' + aid; });
    var rem = r.passed ? [] : E.remediationPlan(r, c.lessons, COMPS);
    app.innerHTML = '<div class="container-wide"><div class="pw-head" style="padding-bottom:1rem"><div><div class="eyebrow"><a href="/learn/' + cid + rq + '">← ' + esc(c.title) + '</a></div><h1>Assessment result</h1><p>Attempt ' + (ids.indexOf(aid) + 1) + ' of ' + ids.length + ' · ' + at.created_at.slice(0, 16).replace('T', ' ') + ' UTC</p></div></div>' +
      '<section class="pw-card result-hero ' + (r.passed ? 'pass' : 'fail') + '">' + ring(r.percent, 'lg', r.passed ? 'var(--done)' : 'var(--rec)') + '<div style="flex:1;min-width:220px"><h3 style="font-size:1.25rem">' + (r.passed ? 'Passed: competency evidence recorded' : 'Not yet: targeted revision below') + '</h3><p class="muted" style="margin-top:.3rem">' + r.correct + ' of ' + r.total + ' correct · pass mark ' + Math.round(r.pass_threshold * 100) + '%. ' +
      (r.passed && c.lab && !c.progress.lab_passed ? 'Complete the practical lab to finish this course.' : r.passed ? 'Course completed.' : 'Your competency levels were <b>not</b> changed.') + '</p></div><div class="btn-row">' +
      (!r.passed ? '<a class="btn btn-primary" href="/learn/' + cid + '/assessment' + rq + '">Retry assessment</a>' : c.lab && !c.progress.lab_passed ? '<a class="btn btn-primary" href="/learn/' + cid + '/lab' + rq + '">Open the lab</a>' : '') +
      (rid ? '<a class="btn btn-brand" href="/roadmaps/' + rid + '">Back to roadmap</a>' : '<a class="btn btn-brand" href="/dashboard">Dashboard</a>') + '</div></section>' +
      '<div class="grid-2 pw-section"><section class="pw-card"><div class="h2" style="font-size:1rem">Per-competency score</div>' + Object.keys(r.per_competency).map(function (k) {
        var s = r.per_competency[k], p = Math.round(s.accuracy * 100);
        return '<div class="dev-row"><span>' + esc(COMPS[k].name) + '</span><span class="xs"><b>' + s.correct + '/' + s.total + '</b> · ' + p + '%</span><div class="bar thin"><span class="fill ' + (s.accuracy >= 0.8 ? 'assessment' : 'self_reported') + '" style="width:' + p + '%"></span><span class="target" style="left:80%"></span></div></div>';
      }).join('') + '<p class="xs muted" style="margin-top:.5rem">Rule: after a pass, each competency is credited at <i>course level × min(1, accuracy ÷ 80%)</i>. The marker shows 80%.</p></section>' +
      '<section class="pw-card"><div class="h2" style="font-size:1rem">What changed in your profile</div>' +
      (fresh.changes && fresh.changes.length ? fresh.changes.map(function (ch) { return '<div class="change"><b style="flex:1;font-weight:600">' + esc(ch.name) + '</b>' + basisTag(ch.before_basis) + '<b>' + ch.before + '</b><span class="arrow">→</span><b style="color:var(--done)">' + ch.after + '</b>' + basisTag(ch.after_basis) + '</div>'; }).join('')
        : ev.length ? ev.map(function (e) { return '<div class="change"><b style="flex:1;font-weight:600">' + esc(COMPS[e.competency].name) + '</b><span class="basis assessment">Evidence</span><b>' + e.level + '</b></div>'; }).join('')
        : '<p class="small muted">No change. ' + (r.passed ? 'Your existing validated levels were already at or above this result.' : 'A failed attempt never changes competency levels.') + '</p>') +
      ev.map(function (e) { return '<p class="xs muted" style="margin-top:.4rem">' + esc(e.note) + '</p>'; }).join('') +
      (fresh.roadmaps && fresh.roadmaps.length ? '<div class="mini-title" style="margin-top:1rem">Roadmaps recalculated</div>' + fresh.roadmaps.map(function (x) { return '<div class="change"><a href="/roadmaps/' + x.id + '" style="flex:1">' + esc(x.goal_title) + '</a><span class="xs muted">readiness</span><b>' + (x.readiness_before == null ? '–' : x.readiness_before) + '%</b><span class="arrow">→</span><b style="color:var(--brand-deep)">' + x.readiness_after + '%</b></div>'; }).join('') : '') + '</section></div>' +
      (rem.length ? '<section class="pw-section"><div class="h2">Targeted revision</div><p class="small muted" style="margin:-.4rem 0 1rem">Built from the questions you missed. Revisit these lessons, then retry.</p><div class="grid-2">' + rem.map(function (m) {
        return '<article class="pw-card remedy"><div class="row between"><h3>' + esc(m.lesson_title) + '</h3>' + chip(m.competency_name) + '</div><ul class="reasons">' + m.missed.map(function (x) { return '<li><b>' + esc(x.question) + '</b><br><span class="muted">' + esc(x.explanation) + '</span></li>'; }).join('') + '</ul><a class="btn btn-soft btn-sm" style="margin-top:.6rem" href="/learn/' + cid + '?lesson=' + m.lesson_id + (rid ? '&roadmap=' + rid : '') + '">Revise this lesson</a></article>';
      }).join('') + '</div></section>' : '') +
      '<section class="pw-section"><div class="h2">Review answers</div>' + r.details.map(function (d, i) {
        return '<fieldset class="q review"><legend><span class="qn">Q' + (i + 1) + '.</span>' + esc(d.text) + ' ' + (d.correct ? chip('Correct', 'ok') : chip(d.chosen == null ? 'Unanswered' : 'Incorrect', 'bad')) + '</legend>' +
          d.options.map(function (o, j) { return '<div class="opt ' + (j === d.answer ? 'correct' : j === d.chosen ? 'wrong' : '') + '">' + esc(o) + (j === d.chosen ? ' <span class="xs muted">(your answer)</span>' : '') + '</div>'; }).join('') +
          '<p class="small muted" style="margin-top:.4rem">' + esc(d.explanation) + '</p></fieldset>';
      }).join('') + '</section></div>';
  }

  function viewLab(cid, q) {
    var L = me(), c = courseForLearner(L, cid); if (!c || !c.lab) throw new Error('This course has no lab.');
    var lab = c.lab, rid = q.roadmap, rq = rid ? '?roadmap=' + rid : '', pr = c.progress, out = flash && flash.lab === cid ? flash : null;
    var form = out ? out.form : {}, res = {};
    if (out) out.result.tasks.forEach(function (t) { res[t.id] = t; });
    var subs = L.labs.filter(function (l) { return l.course_id === cid; });
    var body;
    if (!pr.quiz_passed) body = '<div class="form-error">Pass the course assessment first. The lab unlocks after that.</div><a class="btn btn-primary" href="/learn/' + cid + '/assessment' + rq + '">Take the assessment</a>';
    else {
      var ok = out ? out.result.tasks.filter(function (t) { return t.correct; }).length : 0;
      body = '<div class="grid-side"><div>' + (out ? '<section class="pw-card result-hero ' + (out.result.passed ? 'pass' : 'fail') + '" style="margin-bottom:1.25rem"><div class="ring" style="--p:' + Math.round(100 * ok / out.result.tasks.length) + ';--c:' + (out.result.passed ? 'var(--done)' : 'var(--rec)') + '"><b>' + ok + '/' + out.result.tasks.length + '</b></div><div style="flex:1"><h3>' + (out.result.passed ? 'Lab complete: course finished' : 'Some answers need another look') + '</h3>' +
        out.changes.map(function (ch) { return '<div class="small">' + esc(ch.name) + ': <b>' + ch.before + '</b> → <b style="color:var(--done)">' + ch.after + '</b> (validated)</div>'; }).join('') +
        (!out.result.interpretation_ok ? '<div class="small" style="color:var(--unav)">Add a fuller interpretation (at least ' + lab.min_interpretation_chars + ' characters).</div>' : '') +
        (out.result.passed ? out.roadmaps.map(function (x) { return '<div class="xs muted">' + esc(x.goal_title) + ' roadmap: readiness ' + x.readiness_before + '% → ' + x.readiness_after + '%</div>'; }).join('') : '') + '</div>' + (rid ? '<a class="btn btn-brand" href="/roadmaps/' + rid + '">Back to roadmap</a>' : '') + '</section>' : '') +
        '<section class="pw-card">' + lab.instructions.map(function (p) { return '<p class="small" style="margin-bottom:.6rem;color:var(--ink-2)">' + esc(p) + '</p>'; }).join('') +
        '<div class="table-scroll" style="margin-top:.6rem"><table class="lab-table"><thead><tr>' + lab.dataset.columns.map(function (x) { return '<th>' + esc(x) + '</th>'; }).join('') + '</tr></thead><tbody>' + lab.dataset.rows.map(function (row) { return '<tr>' + row.map(function (v) { return '<td>' + esc(v) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>' +
        '<p class="xs muted" style="margin-top:.4rem">Demonstration dataset (12 households). Weight = households represented. Consumption in ₹ per capita per month.</p></section>' +
        '<form class="pw-card pw-section" id="labForm">' + lab.tasks.map(function (t, i) {
          var rr = res[t.id];
          return '<div class="field"><label for="t_' + t.id + '">' + (i + 1) + '. ' + esc(t.label) + '</label><div class="row" style="flex-wrap:nowrap"><input id="t_' + t.id + '" name="' + t.id + '" inputmode="decimal" value="' + esc(form[t.id] || '') + '" required style="max-width:220px">' + (rr ? chip(rr.correct ? 'Correct' : 'Check again', rr.correct ? 'ok' : 'bad') : '') + '</div><div class="hint">Tolerance ±' + t.tolerance + '</div></div>';
        }).join('') + '<div class="field"><label for="interp">4. Interpretation for a non-technical reader</label><textarea id="interp" rows="4" placeholder="What do the numbers say, and how confident should the reader be?">' + esc(form.interpretation || '') + '</textarea></div>' +
        '<button class="btn btn-primary" type="submit">' + (subs.length ? 'Resubmit' : 'Submit lab') + '</button></form></div>' +
        '<aside><div class="pw-card"><div class="h2" style="font-size:1rem">Hints</div><ul class="reasons"><li>Weighted mean = Σ(weight × consumption) ÷ Σ weight.</li><li>SE of a mean = sample SD (n − 1) ÷ √n.</li><li>Welch t = (mean A − mean B) ÷ √(s²A/nA + s²B/nB).</li></ul><a class="small" href="/learn/' + cid + '?lesson=lab301-2' + (rid ? '&roadmap=' + rid : '') + '">Revisit “Estimation and uncertainty”</a></div>' +
        (subs.length ? '<div class="pw-card pw-section"><div class="h2" style="font-size:1rem">Your submissions</div>' + subs.slice().reverse().map(function (s) { return '<div class="change"><span style="flex:1" class="small">' + s.created_at.slice(0, 16).replace('T', ' ') + '</span>' + chip(s.result.passed ? 'Passed' : 'Not passed', s.result.passed ? 'ok' : 'bad') + '</div>'; }).join('') + '</div>' : '') + '</aside></div>';
    }
    app.innerHTML = '<div class="container-wide"><div class="pw-head"><div><div class="eyebrow"><a href="/learn/' + cid + rq + '">← ' + esc(c.title) + '</a></div><h1>Practical lab: ' + esc(lab.title) + '</h1><p>Numeric answers are checked automatically against values computed from the dataset. Completing the lab records validated evidence for Applied Statistical Analysis.</p></div>' + (pr.lab_passed ? chip('Lab completed', 'ok') : '') + '</div>' + body + '</div>';
    var f = document.getElementById('labForm');
    if (f) f.onsubmit = function (e) {
      e.preventDefault();
      var ans = {}; lab.tasks.forEach(function (t) { ans[t.id] = document.getElementById('t_' + t.id).value; });
      var interp = document.getElementById('interp').value;
      try { var o = submitLab(L, cid, ans, interp); o.lab = cid; o.form = Object.assign({ interpretation: interp }, ans); flash = o; go('/learn/' + cid + '/lab' + rq); }
      catch (x) { PW.toast(x.message, true); }
    };
  }

  function viewCompare(q) {
    var gid = q.goal && GOALS[q.goal] ? q.goal : 'stat_data_analyst';
    app.innerHTML = '<div class="container-wide"><div class="pw-head"><div><div class="eyebrow">Same goal, same engine, different learners</div><h1>Compare demo learners</h1><p>Both journeys below are generated live from each demo learner’s current competency evidence. Nothing is hard-coded per user.</p></div>' +
      '<div class="row"><label for="goalSel" class="small" style="margin:0">Goal</label><select id="goalSel" style="width:auto">' + D.goals.map(function (g) { return '<option value="' + g.id + '"' + (g.id === gid ? ' selected' : '') + '>' + esc(g.title) + '</option>'; }).join('') + '</select></div></div>' +
      '<div class="grid-2" id="cols"></div>' + banner('Asha and Ravi are fictional demonstration profiles. Pick either one from <b>Switch learner</b> (top-right menu) to take their journey. <button class="linkish" id="resetDemo">Reset both demo learners</button> to restore their starting profiles.') + '</div>';
    document.getElementById('goalSel').onchange = function () { go('/compare?goal=' + this.value, true); };
    document.getElementById('resetDemo').onclick = function () { D.demo_learners.forEach(function (d) { S.users[d.username] = seedDemo(d); }); save(); go('/compare?goal=' + gid, true); PW.toast('Demo learners reset to their starting profiles.'); };
    var BL = { assessment: 'Validated', self_reported: 'Self-reported', none: 'No evidence' };
    var cols = document.getElementById('cols');
    var learners = D.demo_learners.map(function (d) {
      var L = S.users[d.username], rec = L.roadmaps[gid], pc = [], pe = [];
      if (rec) { pc = rec.graph.course_ids; pe = rec.graph.dependency_edges; }
      return { d: d, L: L, rm: E.buildRoadmap(GOALS[gid], COURSES, levels(L), progress(L), COMPS, null, pc, pe, L.display_name) };
    });
    cols.innerHTML = learners.map(function (x) {
      var rm = x.rm, a = rm.analysis;
      var deps = rm.dependency_edges.length ? rm.dependency_edges.map(function (t) { return esc(t[0]) + ' → ' + esc(t[1]); }).join(', ') : 'none: starts directly on goal-level courses';
      return '<div class="compare-col"><div class="pw-card"><div class="row" style="gap:.9rem">' + ring(a.readiness) + '<div style="min-width:0"><h3>' + esc(x.L.display_name) + '</h3><div class="xs muted">' + esc(x.d.education) + ' · ' + x.d.experience_years + ' yrs</div><div class="xs muted">' + rm.summary.courses_total + ' courses on the roadmap · prerequisite links: ' + deps + '</div></div></div></div>' +
        '<div class="pw-card"><div class="mini-title">Generated roadmap</div><div class="mini-rm"><div class="rm-canvas" data-mini></div></div><p class="xs muted" style="margin-top:.4rem">Drag or scroll to explore.</p></div>' +
        '<div class="pw-card"><div class="mini-title">Recommendations, in order</div>' + a.recommendations.map(function (r) {
          return '<div class="rec-line"><span class="rec-rank" style="width:24px;height:24px;font-size:.75rem">' + r.rank + '</span><div style="flex:1;min-width:0"><b>' + esc(r.title) + '</b> ' + chip(r.status, r.status === 'ready' ? 'brand' : r.status === 'locked' ? 'lock' : 'bad') + '<div class="xs muted">' + esc(r.reasons[0] || '') + '</div></div></div>';
        }).join('') + (a.skipped.filter(function (s) { return s.kind === 'prereq_met' || s.kind === 'already_met'; }).map(function (s, i) {
          return (i === 0 ? '<div class="mini-title" style="margin-top:.8rem">Not needed for this learner</div>' : '') + '<div class="rec-line">' + chip('Skipped', 'ok') + '<div class="small" style="min-width:0"><b>' + esc(s.title) + '</b><div class="xs muted">' + esc(s.reason) + '</div></div></div>';
        }).join('')) + '</div>' +
        '<div class="pw-card"><div class="mini-title">Current competency vs goal</div>' + a.gaps.map(function (g) {
          return '<div class="dev-row"><span class="small">' + esc(g.name) + ' <span class="basis ' + g.basis + '">' + BL[g.basis] + '</span></span><span class="xs muted">' + g.current + ' / ' + g.target + '</span>' + bar(g.current, g.target, g.gap ? g.target : null, g.basis, true) + '</div>';
        }).join('') + '</div></div>';
    }).join('');
    var minis = cols.querySelectorAll('[data-mini]');
    requestAnimationFrame(function () {
      learners.forEach(function (x, i) {
        var m = new PWRoadmap.Roadmap(minis[i], { compact: true });
        m.render({ nodes: x.rm.nodes, edges: x.rm.edges, width: x.rm.size.width, height: x.rm.size.height });
      });
    });
  }

  // ------------------------------------------------------------------ boot
  load();
  go(S.current ? (S.path || '/dashboard') : '/');
})();
