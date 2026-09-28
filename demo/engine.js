/* AntahAI Learning Pathways - browser port of pathways/engine.py + pathways/rules.py.
 * Pure functions, same rules and tie-breaks as the Python originals (a parity
 * test in demo/parity_test.js compares both on every demo learner x goal). */
(function (root) {
  'use strict';

  // ---------- python-compatible helpers ----------
  function pyRound(x, nd) {
    if (nd) return Number(x.toFixed(nd)); // exact-binary rounding, like Python's round(x, n)
    var f = 1, v = x * f, r = Math.round(v);
    if (Math.abs(v - Math.trunc(v)) === 0.5) r = 2 * Math.round(v / 2); // banker's rounding
    return r / f;
  }
  function cmp(a, b) {
    if (Array.isArray(a)) {
      for (var i = 0; i < Math.min(a.length, b.length); i++) { var c = cmp(a[i], b[i]); if (c) return c; }
      return a.length - b.length;
    }
    return a < b ? -1 : a > b ? 1 : 0;
  }
  function sortBy(arr, keyFn) { return arr.slice().sort(function (x, y) { return cmp(keyFn(x), keyFn(y)); }); }
  function minBy(arr, keyFn) { var best = arr[0]; arr.forEach(function (x) { if (cmp(keyFn(x), keyFn(best)) < 0) best = x; }); return best; }
  function sum(a) { return a.reduce(function (s, x) { return s + x; }, 0); }
  function keys(o) { return Object.keys(o || {}); }
  function titleCase(s) { return String(s || '').replace(/\w\S*/g, function (w) { return w[0].toUpperCase() + w.slice(1).toLowerCase(); }); }

  var DEFAULT_WEIGHTS = { gap_coverage: 0.50, goal_relevance: 0.25, prereq_readiness: 0.15, level_fit: 0.10 };
  var DIFFICULTY_RANK = { beginner: 0, intermediate: 1, advanced: 2 };
  var BAND = [35, 65];
  var NODE_SIZE = { start: [230, 120], course: [250, 118], assessment: [176, 64], lab: [196, 72], milestone: [200, 70], goal: [250, 130] };
  var LAYER_GAP = 70, ROW_GAP = 46, WAVE_AMPLITUDE = 70, WAVE_FREQUENCY = 0.95;

  function CycleError(cycle) { this.name = 'PrerequisiteCycleError'; this.cycle = cycle; this.message = 'Prerequisite cycle detected: ' + cycle.join(' -> ') + '. Fix the course prerequisite definitions; no roadmap was generated.'; }
  CycleError.prototype = Object.create(Error.prototype);

  function normalizeWeights(w) {
    var m = Object.assign({}, DEFAULT_WEIGHTS);
    keys(w).forEach(function (k) { if (k in m) m[k] = Math.max(0, +w[k]); });
    var t = sum(keys(m).map(function (k) { return m[k]; }));
    if (t <= 0) { m = Object.assign({}, DEFAULT_WEIGHTS); t = 1; }
    keys(m).forEach(function (k) { m[k] = m[k] / t; });
    return m;
  }
  function levelOf(lv, c) { var e = lv[c]; return e ? (e.level | 0) : 0; }
  function basisOf(lv, c) { var e = lv[c]; return (e && e.basis) || 'none'; }
  function band(l) { return l < BAND[0] ? 0 : l < BAND[1] ? 1 : 2; }
  function compName(comps, c) { return (comps[c] || {}).name || c; }
  function available(c) { return (c.availability || 'available') === 'available'; }

  // ---------- gaps ----------
  function computeGaps(goal, lv, comps) {
    var rows = goal.requirements.map(function (r) {
      var cur = levelOf(lv, r.competency), gap = Math.max(0, r.target - cur);
      return { competency: r.competency, name: compName(comps, r.competency), current: cur, target: r.target,
        gap: gap, weight: r.weight || 1, basis: basisOf(lv, r.competency), met: gap === 0,
        no_evidence: basisOf(lv, r.competency) === 'none' };
    });
    return sortBy(rows, function (r) { return [-r.gap * r.weight, r.competency]; });
  }
  function goalReadiness(gaps) {
    var num = sum(gaps.map(function (r) { return r.weight * Math.min(r.current, r.target); }));
    var den = sum(gaps.map(function (r) { return r.weight * r.target; }));
    return den ? pyRound(100 * num / den) : 100;
  }

  // ---------- prerequisites ----------
  function prerequisiteStatus(course, lv, comps) {
    return (course.prerequisites || []).map(function (p) {
      var have = levelOf(lv, p.competency);
      return { competency: p.competency, name: compName(comps, p.competency), min_level: p.min_level,
        current: have, satisfied: have >= p.min_level, basis: basisOf(lv, p.competency) };
    });
  }
  function unmetPrereqs(course, lv) {
    return (course.prerequisites || []).filter(function (p) { return levelOf(lv, p.competency) < p.min_level; });
  }
  function detectCycles(courses) {
    var ids = courses.map(function (c) { return c.id; }), edges = {};
    ids.forEach(function (i) { edges[i] = []; });
    courses.forEach(function (course) {
      (course.prerequisites || []).forEach(function (pre) {
        courses.forEach(function (p) {
          if (p.id !== course.id && ((p.develops || {})[pre.competency] || 0) >= pre.min_level) edges[p.id].push(course.id);
        });
      });
    });
    var colour = {}, stack = [];
    ids.forEach(function (i) { colour[i] = 0; });
    function visit(n) {
      colour[n] = 1; stack.push(n);
      Array.from(new Set(edges[n])).sort().forEach(function (nx) {
        if (colour[nx] === 1) throw new CycleError(stack.slice(stack.indexOf(nx)).concat([nx]));
        if (colour[nx] === 0) visit(nx);
      });
      stack.pop(); colour[n] = 2;
    }
    ids.slice().sort().forEach(function (i) { if (colour[i] === 0) visit(i); });
  }

  // ---------- scoring ----------
  function scoreCourse(course, gaps, lv, weights) {
    var w = normalizeWeights(weights), dev = course.develops || {}, gr = {};
    gaps.forEach(function (g) { gr[g.competency] = g; });
    var totalGap = sum(gaps.map(function (g) { return g.weight * g.gap; })), closable = 0;
    keys(dev).forEach(function (c) { var g = gr[c]; if (g && g.gap > 0) closable += g.weight * Math.max(0, Math.min(dev[c], g.target) - g.current); });
    var cov = totalGap ? closable / totalGap : 0;
    var dk = keys(dev);
    var rel = dk.length ? sum(dk.map(function (c) { return gr[c] ? gr[c].weight / 3 : 0; })) / dk.length : 0;
    var pre = course.prerequisites || [];
    var ready = pre.length ? sum(pre.map(function (p) { return Math.min(1, levelOf(lv, p.competency) / Math.max(1, p.min_level)); })) / pre.length : 1;
    var mean = dk.length ? sum(dk.map(function (c) { return levelOf(lv, c); })) / dk.length : 0;
    var fit = 1 - Math.abs((DIFFICULTY_RANK[course.difficulty] || 0) - band(mean)) / 2;
    var comp = { gap_coverage: pyRound(cov, 4), goal_relevance: pyRound(rel, 4), prereq_readiness: pyRound(ready, 4), level_fit: pyRound(fit, 4) };
    var total = sum(keys(comp).map(function (k) { return w[k] * comp[k]; }));
    return { total: pyRound(total, 4), components: comp, weights: w };
  }

  // ---------- plan ----------
  function providerKey(c, comp) { return [available(c) ? 0 : 1, DIFFICULTY_RANK[c.difficulty] || 0, -((c.develops || {})[comp] || 0), c.id]; }

  function selectPlan(goal, courses, lv, completed, comps, weights, revision) {
    detectCycles(courses);
    var byId = {}; courses.forEach(function (c) { byId[c.id] = c; });
    var gaps = computeGaps(goal, lv, comps), targets = {}, wt = {}, proj = {};
    gaps.forEach(function (g) { targets[g.competency] = g.target; wt[g.competency] = g.weight; proj[g.competency] = g.current; });
    var plan = { selected: [], prereq_added: {}, dependencies: [], unresolved: {}, uncovered: [], skipped: [] };
    var eligible = courses.filter(function (c) { return revision || !completed.has(c.id); });
    function marginal(c) {
      var g = 0; keys(c.develops).forEach(function (k) { if (k in targets) g += wt[k] * Math.max(0, Math.min(c.develops[k], targets[k]) - proj[k]); }); return g;
    }
    [true, false].forEach(function (poolAvail) {
      for (;;) {
        var best = null, bestKey = null;
        eligible.forEach(function (c) {
          if (plan.selected.indexOf(c.id) >= 0 || available(c) !== poolAvail) return;
          var gain = marginal(c); if (gain <= 0) return;
          var key = [-gain, -scoreCourse(c, gaps, lv, weights).total, DIFFICULTY_RANK[c.difficulty] || 0, c.id];
          if (bestKey === null || cmp(key, bestKey) < 0) { best = c; bestKey = key; }
        });
        if (!best) break;
        plan.selected.push(best.id);
        keys(best.develops).forEach(function (k) { if (k in proj) proj[k] = Math.max(proj[k], Math.min(best.develops[k], targets[k])); });
      }
    });
    plan.uncovered = keys(targets).filter(function (c) { return proj[c] < targets[c]; });

    var inPlan = plan.selected.slice();
    function resolve(cid, trail) {
      if (trail.indexOf(cid) >= 0) throw new CycleError(trail.slice(trail.indexOf(cid)).concat([cid]));
      unmetPrereqs(byId[cid], lv).forEach(function (pre) {
        var comp = pre.competency, need = pre.min_level;
        var providers = courses.filter(function (p) { return p.id !== cid && ((p.develops || {})[comp] || 0) >= need && !completed.has(p.id); });
        if (!providers.length) { (plan.unresolved[cid] = plan.unresolved[cid] || []).push(pre); return; }
        var already = providers.filter(function (p) { return inPlan.indexOf(p.id) >= 0; });
        var prov = minBy(already.length ? already : providers, function (p) { return providerKey(p, comp); });
        plan.dependencies.push([prov.id, cid, comp]);
        if (inPlan.indexOf(prov.id) < 0) {
          inPlan.push(prov.id);
          (plan.prereq_added[prov.id] = plan.prereq_added[prov.id] || []).push(cid);
          resolve(prov.id, trail.concat([cid]));
        } else if (plan.prereq_added[prov.id] && plan.prereq_added[prov.id].indexOf(cid) < 0) {
          plan.prereq_added[prov.id].push(cid);
        }
      });
    }
    plan.selected.slice().forEach(function (cid) { resolve(cid, []); });

    var planIds = new Set(inPlan), explained = new Set();
    inPlan.forEach(function (cid) {
      (byId[cid].prerequisites || []).forEach(function (pre) {
        var comp = pre.competency, need = pre.min_level, have = levelOf(lv, comp);
        if (have < need) return;
        courses.forEach(function (p) {
          if (planIds.has(p.id) || explained.has(p.id) || p.id === cid) return;
          if (((p.develops || {})[comp] || 0) < need) return;
          if (keys(p.develops).some(function (c) { return c in targets; })) return;
          var b = basisOf(lv, comp) === 'assessment' ? ' (assessment-validated)' : ' (self-reported)';
          plan.skipped.push({ course_id: p.id, title: p.title, kind: 'prereq_met',
            reason: 'Not needed: ' + byId[cid].title + ' requires ' + compName(comps, comp) + ' ≥ ' + need + ' and you are at ' + have + b + '.' });
          explained.add(p.id);
        });
      });
    });
    courses.forEach(function (c) {
      if (explained.has(c.id) || planIds.has(c.id)) return;
      var touches = keys(c.develops).filter(function (k) { return k in targets; });
      if (!touches.length) return;
      var kind, reason;
      if (completed.has(c.id) && !revision) { kind = 'completed'; reason = 'Already completed - excluded (request revision to include it).'; }
      else if (touches.every(function (k) { return proj[k] >= targets[k] && levelOf(lv, k) >= targets[k]; })) {
        kind = 'already_met';
        reason = 'You already meet the goal level for ' + touches.map(function (k) {
          return compName(comps, k) + ' (' + levelOf(lv, k) + (basisOf(lv, k) === 'assessment' ? ', validated' : '') + ')';
        }).join(', ') + '.';
      } else { kind = 'redundant'; reason = 'Another selected course already closes the same gap.'; }
      plan.skipped.push({ course_id: c.id, title: c.title, kind: kind, reason: reason });
    });
    plan.selected = inPlan;
    return plan;
  }

  // ---------- recommendations ----------
  function buildRecommendations(goal, courses, lv, progress, comps, weights, revision, plan) {
    var completed = new Set(keys(progress).filter(function (k) { return progress[k].status === 'completed'; }));
    plan = plan || selectPlan(goal, courses, lv, completed, comps, weights, revision);
    var byId = {}; courses.forEach(function (c) { byId[c.id] = c; });
    var gaps = computeGaps(goal, lv, comps), gr = {};
    gaps.forEach(function (g) { gr[g.competency] = g; });
    var recs = [];
    plan.selected.forEach(function (cid) {
      var c = byId[cid];
      if (completed.has(cid) && !revision) return;
      var score = scoreCourse(c, gaps, lv, weights), pre = prerequisiteStatus(c, lv, comps);
      var unmet = pre.filter(function (p) { return !p.satisfied; });
      var status = !available(c) ? 'unavailable' : unmet.length ? 'locked' : 'ready';
      var develops = [], changes = [];
      keys(c.develops).forEach(function (k) {
        var g = gr[k];
        develops.push({ competency: k, name: compName(comps, k), course_reaches: c.develops[k], current: levelOf(lv, k),
          target: g ? g.target : null, basis: basisOf(lv, k), in_goal: !!g });
        if (g && g.gap > 0) changes.push([g.name, g.current, c.develops[k], g.target]);
      });
      var reasons = [];
      if (changes.length) reasons.push('Closes ' + pyRound(score.components.gap_coverage * 100) + '% of your weighted gap for ' + goal.title + ': ' +
        changes.map(function (x) { return x[0] + ' ' + x[1] + ' → ' + Math.min(x[2], x[3]) + ' (goal ' + x[3] + ')'; }).join('; ') + '.');
      if (plan.prereq_added[cid]) {
        var deps = plan.prereq_added[cid].map(function (d) { return byId[d].title; }).join(', ');
        var needed = {};
        plan.dependencies.forEach(function (t) {
          if (t[0] !== cid) return;
          (byId[t[1]].prerequisites || []).forEach(function (p) { if (p.competency === t[2]) needed[t[2]] = Math.max(needed[t[2]] || 0, p.min_level); });
        });
        reasons.push('Foundation step: ' + deps + ' requires ' + keys(needed).sort().map(function (k) {
          return compName(comps, k) + ' ≥ ' + needed[k] + ' (you: ' + levelOf(lv, k) + ')';
        }).join(', ') + '.');
      }
      if (status === 'locked') reasons.push('Locked until: ' + unmet.map(function (p) { return p.name + ' ≥ ' + p.min_level + ' (you: ' + p.current + ')'; }).join('; ') + '.');
      else if (status === 'unavailable') reasons.push('No available content: this is an unverified external listing, so it cannot be started here.');
      else if (pre.length) reasons.push('All prerequisites met.');
      else reasons.push('No prerequisites - you can start immediately.');
      var missing = develops.filter(function (d) { return d.in_goal && d.basis === 'none'; }).map(function (d) { return d.name; });
      if (missing.length) reasons.push('No evidence yet for ' + missing.join(', ') + ' - treated as 0 until you self-report or pass an assessment.');
      recs.push({ course_id: cid, title: c.title, summary: c.summary || '', outcomes: c.outcomes || [], difficulty: c.difficulty,
        duration_minutes: c.duration_verified ? c.duration_minutes : null, availability: c.availability || 'available',
        source: c.source || 'local', status: status, role: (plan.prereq_added[cid] && !changes.length) ? 'prerequisite' : 'gap',
        score: score, develops: develops, prerequisites: pre, reasons: reasons,
        progress: progress[cid] || { status: 'not_started', percent: 0 } });
    });
    var order = { ready: 0, locked: 1, unavailable: 2 };
    recs = sortBy(recs, function (r) { return [order[r.status], -r.score.total, r.course_id]; });
    recs.forEach(function (r, i) { r.rank = i + 1; });
    return { goal: { id: goal.id, title: goal.title }, gaps: gaps, readiness: goalReadiness(gaps), recommendations: recs,
      skipped: plan.skipped, uncovered: plan.uncovered.map(function (c) { return { competency: c, name: compName(comps, c) }; }),
      weights: normalizeWeights(weights) };
  }

  // ---------- roadmap ----------
  function courseState(c, lv, progress) {
    var p = progress[c.id] || {};
    if (p.status === 'completed') return 'completed';
    if (!available(c)) return 'unavailable';
    if (unmetPrereqs(c, lv).length) return 'locked';
    if (p.status === 'in_progress') return 'in_progress';
    return 'available';
  }

  function buildRoadmap(goal, courses, lv, progress, comps, weights, preservedCourses, preservedEdges, learnerName) {
    var completed = new Set(keys(progress).filter(function (k) { return progress[k].status === 'completed'; }));
    var byId = {}; courses.forEach(function (c) { byId[c.id] = c; });
    var plan = selectPlan(goal, courses, lv, completed, comps, weights, false);
    var rec = buildRecommendations(goal, courses, lv, progress, comps, weights, false, plan);
    var gaps = rec.gaps, gr = {};
    gaps.forEach(function (g) { gr[g.competency] = g; });
    var courseIds = plan.selected.slice();
    (preservedCourses || []).forEach(function (cid) { if (byId[cid] && completed.has(cid) && courseIds.indexOf(cid) < 0) courseIds.push(cid); });

    var nodes = {}, nodeOrder = [], edges = {}, edgeOrder = [];
    function addNode(n) { if (!nodes[n.id]) nodeOrder.push(n.id); nodes[n.id] = n; }
    function addEdge(s, t, kind, label) {
      var id = s + '->' + t; if (s === t || edges[id]) return;
      edges[id] = { id: id, source: s, target: t, kind: kind || 'flow', label: label || '' }; edgeOrder.push(id);
    }
    addNode({ id: 'start', type: 'start', state: 'completed', title: learnerName || 'You', subtitle: 'Current competency state',
      data: { readiness: rec.readiness,
        met: gaps.filter(function (g) { return g.met && !courseIds.some(function (c) { return g.competency in byId[c].develops; }); })
          .map(function (g) { return { competency: g.competency, name: g.name, level: g.current, basis: g.basis }; }),
        levels: gaps.map(function (g) { return { competency: g.competency, name: g.name, current: g.current, target: g.target, basis: g.basis }; }) } });
    var recsById = {}; rec.recommendations.forEach(function (r) { recsById[r.course_id] = r; });
    var ready = rec.recommendations.filter(function (r) { return r.status === 'ready'; });
    var nextId = ready.length ? ready[0].course_id : null;
    var chainEnd = {};
    courseIds.forEach(function (cid) {
      var c = byId[cid], state = courseState(c, lv, progress), info = recsById[cid], ps = progress[cid] || {};
      addNode({ id: 'course:' + cid, type: 'course', state: state, course_id: cid, title: c.title, subtitle: titleCase(c.difficulty),
        recommended: cid === nextId,
        data: { summary: c.summary || '', outcomes: c.outcomes || [], duration_minutes: c.duration_verified ? c.duration_minutes : null,
          source: c.source || 'local', availability: c.availability || 'available',
          develops: keys(c.develops).map(function (k) { return { competency: k, name: compName(comps, k), reaches: c.develops[k], current: levelOf(lv, k), target: gr[k] ? gr[k].target : null }; }),
          prerequisites: prerequisiteStatus(c, lv, comps),
          reasons: info ? info.reasons : ['Completed earlier - kept as learning history.'],
          score: info ? info.score : null, rank: info ? info.rank : null,
          progress: { status: ps.status || 'not_started', percent: ps.percent | 0 } } });
      var end = 'course:' + cid;
      if (c.has_quiz && available(c)) {
        var qs = (ps.quiz_passed || state === 'completed') ? 'completed' : state === 'locked' ? 'locked' : ps.quiz_attempts ? 'in_progress' : 'available';
        addNode({ id: 'quiz:' + cid, type: 'assessment', state: qs, course_id: cid, title: 'Assessment', subtitle: c.title,
          data: { best_score: ps.best_score == null ? null : ps.best_score, attempts: ps.quiz_attempts || 0 } });
        addEdge(end, 'quiz:' + cid); end = 'quiz:' + cid;
      }
      if (c.has_lab && available(c)) {
        addNode({ id: 'lab:' + cid, type: 'lab', state: ps.lab_passed ? 'completed' : !ps.quiz_passed ? 'locked' : 'available',
          course_id: cid, title: 'Practical lab', subtitle: c.lab_title || '', data: {} });
        addEdge(end, 'lab:' + cid); end = 'lab:' + cid;
      }
      chainEnd[cid] = end;
    });
    var hasIn = new Set();
    plan.dependencies.forEach(function (t) {
      if (chainEnd[t[0]] && chainEnd[t[1]]) { addEdge(chainEnd[t[0]], 'course:' + t[1], 'prerequisite', compName(comps, t[2])); hasIn.add(t[1]); }
    });
    (preservedEdges || []).forEach(function (t) {
      if (chainEnd[t[0]] && chainEnd[t[1]] && completed.has(t[0])) { addEdge(chainEnd[t[0]], 'course:' + t[1], 'prerequisite'); hasIn.add(t[1]); }
    });
    courseIds.forEach(function (cid) { if (!hasIn.has(cid)) addEdge('start', 'course:' + cid); });
    var goalState = gaps.every(function (g) { return g.met; }) ? 'completed' : 'locked';
    gaps.forEach(function (g) {
      var k = g.competency, contrib = courseIds.filter(function (cid) { return k in byId[cid].develops; });
      if (!contrib.length && g.met) return;
      var mid = 'milestone:' + k;
      var ms = g.met ? 'completed' : (contrib.length && contrib.every(function (c) { return !available(byId[c]); })) || !contrib.length ? 'unavailable' : 'locked';
      addNode({ id: mid, type: 'milestone', state: ms, title: g.name, subtitle: 'Reach ' + g.target,
        data: { current: g.current, target: g.target, basis: g.basis, no_course: !contrib.length } });
      if (contrib.length) contrib.forEach(function (cid) { addEdge(chainEnd[cid], mid, 'milestone'); });
      else addEdge('start', mid, 'gap', 'no course available');
      addEdge(mid, 'goal', 'goal');
    });
    addNode({ id: 'goal', type: 'goal', state: goalState, title: goal.title, subtitle: 'Goal destination',
      data: { readiness: rec.readiness, tagline: goal.tagline || '' } });
    if (!edgeOrder.some(function (id) { return edges[id].target === 'goal'; })) addEdge('start', 'goal', 'goal');

    var nodeList = nodeOrder.map(function (id) { return nodes[id]; }), edgeList = edgeOrder.map(function (id) { return edges[id]; });
    if (topologicalOrder(nodeList, edgeList).length !== nodeList.length) throw new CycleError(['roadmap']);
    var size = layout(nodeList, edgeList);
    var pc = nodeList.filter(function (n) { return n.type === 'course'; });
    var done = pc.filter(function (n) { return n.state === 'completed'; }).length;
    var startable = sortBy(pc.filter(function (n) { return n.state === 'available' || n.state === 'in_progress'; }),
      function (n) { return [n.state === 'in_progress' ? 0 : 1, n.data.rank || 99]; });
    var next = startable.length ? { course_id: startable[0].course_id, title: startable[0].title, verb: startable[0].state === 'in_progress' ? 'Continue' : 'Start' } : null;
    var deps = {}; plan.dependencies.forEach(function (t) { deps[t[0] + '\u0000' + t[1]] = [t[0], t[1]]; });
    return { goal: { id: goal.id, title: goal.title, tagline: goal.tagline || '' }, nodes: nodeList, edges: edgeList,
      size: { width: size[0], height: size[1] },
      summary: { courses_total: pc.length, courses_completed: done, progress: pc.length ? pyRound(100 * done / pc.length) : 100,
        readiness: rec.readiness, next_action: next },
      analysis: rec, course_ids: courseIds, dependency_edges: sortBy(keys(deps).map(function (k) { return deps[k]; }), function (x) { return x; }) };
  }

  function topologicalOrder(nodes, edges) {
    var indeg = {}, out = {};
    nodes.forEach(function (n) { indeg[n.id] = 0; out[n.id] = []; });
    edges.forEach(function (e) { out[e.source].push(e.target); indeg[e.target]++; });
    var ready = keys(indeg).filter(function (n) { return indeg[n] === 0; }).sort(), order = [];
    while (ready.length) {
      var n = ready.shift(); order.push(n);
      out[n].slice().sort().forEach(function (x) { if (--indeg[x] === 0) ready.push(x); });
      ready.sort();
    }
    return order;
  }

  function layout(nodes, edges) {
    var byId = {}, preds = {}, succs = {};
    nodes.forEach(function (n) { byId[n.id] = n; preds[n.id] = []; succs[n.id] = []; });
    edges.forEach(function (e) { preds[e.target].push(e.source); succs[e.source].push(e.target); });
    var layer = {}, layerOrder = [];
    topologicalOrder(nodes, edges).forEach(function (id) {
      layer[id] = 1 + (preds[id].length ? Math.max.apply(null, preds[id].map(function (p) { return layer[p]; })) : -1);
      layerOrder.push(id);
    });
    var ms = layerOrder.filter(function (n) { return byId[n].type === 'milestone'; });
    if (ms.length) { var mc = Math.max.apply(null, ms.map(function (n) { return layer[n]; })); ms.forEach(function (n) { layer[n] = mc; }); }
    var last = Math.max.apply(null, layerOrder.map(function (n) { return layer[n]; }).concat([0]));
    if ('goal' in layer) {
      var others = layerOrder.filter(function (n) { return n !== 'goal'; }).map(function (n) { return layer[n]; });
      layer.goal = others.length ? Math.max.apply(null, others) + 1 : 0; last = layer.goal;
    }
    var columns = {}, colKeys = [];
    layerOrder.forEach(function (id) { var l = layer[id]; if (!columns[l]) { columns[l] = []; colKeys.push(l); } columns[l].push(id); });
    var TR = { start: 0, course: 1, assessment: 2, lab: 3, milestone: 4, goal: 5 };
    colKeys.forEach(function (l) { columns[l] = sortBy(columns[l], function (n) { return [TR[byId[n].type], n]; }); });
    var pos = {};
    colKeys.forEach(function (l) { columns[l].forEach(function (id, i) { pos[id] = i; }); });
    function crossings() {
      var t = 0, pairs = edges.map(function (e) { return [pos[e.source], pos[e.target], layer[e.source]]; });
      for (var i = 0; i < pairs.length; i++) for (var j = i + 1; j < pairs.length; j++)
        if (pairs[i][2] === pairs[j][2] && (pairs[i][0] - pairs[j][0]) * (pairs[i][1] - pairs[j][1]) < 0) t++;
      return t;
    }
    function snap() { var o = {}; colKeys.forEach(function (l) { o[l] = columns[l].slice(); }); return o; }
    var best = [snap(), crossings()], order = colKeys.slice().sort(function (a, b) { return a - b; });
    for (var it = 0; it < 6; it++) {
      var fwd = it % 2 === 0, seq = fwd ? order.slice(1) : order.slice(0, -1).reverse(), ref = fwd ? preds : succs;
      seq.forEach(function (l) {
        var bary = function (id) { var ps = ref[id].filter(function (p) { return p in pos; }).map(function (p) { return pos[p]; }); return ps.length ? sum(ps) / ps.length : (pos[id] || 0); };
        columns[l] = sortBy(columns[l], function (id) { return [bary(id), id]; });
        columns[l].forEach(function (id, i) { pos[id] = i; });
      });
      var sc = crossings(); if (sc < best[1]) best = [snap(), sc];
    }
    columns = best[0];
    var x = 0, minY = Infinity, maxY = -Infinity;
    for (var l = 0; l <= last; l++) {
      var col = columns[l] || []; if (!col.length) continue;
      var cw = Math.max.apply(null, col.map(function (id) { return NODE_SIZE[byId[id].type][0]; }));
      var hs = col.map(function (id) { return NODE_SIZE[byId[id].type][1]; });
      var th = sum(hs) + ROW_GAP * (col.length - 1);
      var wave = (l > 0 && l < last) ? WAVE_AMPLITUDE * Math.sin(l * WAVE_FREQUENCY) : 0;
      var y = -th / 2 + wave, cx = x + cw / 2;
      col.forEach(function (id, i) {
        var n = byId[id], h = hs[i];
        n.layer = l; n.x = pyRound(cx, 1); n.y = pyRound(y + h / 2, 1);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y + h); y += h + ROW_GAP;
      });
      x += cw + LAYER_GAP;
    }
    var pad = 60, oy = pad - (isFinite(minY) ? minY : 0);
    nodes.forEach(function (n) { n.x = pyRound((n.x || 0) + pad, 1); n.y = pyRound((n.y || 0) + oy, 1); });
    return [Math.trunc(x - LAYER_GAP + 2 * pad), Math.trunc((isFinite(maxY) ? maxY - minY : 0) + 2 * pad)];
  }

  // ---------- rules ----------
  var CONFIDENCE = { assessment: 0.9, self_reported: 0.5, resume_inferred: 0.3 }, MASTERY = 0.8;

  function effectiveLevels(evidence) {
    var groups = {}, order = [], out = {};
    evidence.forEach(function (r) { var c = r.competency; if (!groups[c]) { groups[c] = []; order.push(c); } groups[c].push(r); });
    order.forEach(function (c) {
      var rows = groups[c];
      var as = rows.filter(function (r) { return r.source === 'assessment'; }), sr = rows.filter(function (r) { return r.source === 'self_reported'; });
      var inf = rows.filter(function (r) { return r.source === 'resume_inferred' && !r.confirmed; });
      var e = { level: 0, basis: 'none', confidence: 0, self_reported: sr.length ? sr[sr.length - 1].level : null,
        assessed: as.length ? Math.max.apply(null, as.map(function (r) { return r.level; })) : null,
        suggested: inf.length ? Math.max.apply(null, inf.map(function (r) { return r.level; })) : null, explanation: '' };
      if (as.length) {
        var best = as.reduce(function (a, b) { return b.level > a.level ? b : a; });
        e.level = best.level; e.basis = 'assessment'; e.confidence = CONFIDENCE.assessment; e.explanation = best.note || 'Validated by assessment.';
        if (e.self_reported != null && e.self_reported > e.level) e.explanation += ' Self-rating (' + e.self_reported + ') is higher than the validated level; the validated level is used.';
      } else if (sr.length) {
        e.level = sr[sr.length - 1].level; e.basis = 'self_reported'; e.confidence = CONFIDENCE.self_reported; e.explanation = 'Self-reported, not yet validated by an assessment.';
      } else e.explanation = inf.length ? 'Only a resume suggestion exists - confirm it to use it.' : 'No evidence.';
      out[c] = e;
    });
    return out;
  }

  function gradeQuiz(questions, answers, threshold) {
    var per = {}, perOrder = [], details = [], ok = 0;
    questions.forEach(function (q) {
      var ch = answers[q.id], right = ch != null && +ch === q.answer;
      if (right) ok++;
      if (!per[q.competency]) { per[q.competency] = [0, 0]; perOrder.push(q.competency); }
      per[q.competency][1]++; if (right) per[q.competency][0]++;
      details.push({ id: q.id, text: q.text, options: q.options, chosen: ch == null ? null : +ch, answer: q.answer, correct: right,
        competency: q.competency, lesson: q.lesson, explanation: q.explanation || '' });
    });
    var total = questions.length, score = total ? ok / total : 0, pc = {};
    perOrder.forEach(function (c) { pc[c] = { correct: per[c][0], total: per[c][1], accuracy: pyRound(per[c][0] / per[c][1], 4) }; });
    return { correct: ok, total: total, score: pyRound(score, 4), percent: pyRound(score * 100), passed: total > 0 && score + 1e-9 >= threshold,
      pass_threshold: threshold, per_competency: pc, details: details };
  }
  function remediationPlan(result, lessons, comps) {
    var byL = {}, g = {};
    lessons.forEach(function (l) { byL[l.id] = l; });
    result.details.forEach(function (d) {
      if (d.correct || !byL[d.lesson]) return;
      var e = g[d.lesson] = g[d.lesson] || { lesson_id: d.lesson, lesson_title: byL[d.lesson].title, competency: d.competency,
        competency_name: compName(comps, d.competency), missed: [] };
      e.missed.push({ question: d.text, explanation: d.explanation });
    });
    var ids = lessons.map(function (l) { return l.id; });
    return sortBy(keys(g).map(function (k) { return g[k]; }), function (e) { return ids.indexOf(e.lesson_id); });
  }
  function assessmentEvidence(course, result) {
    if (!result.passed) return [];
    return keys(course.develops).filter(function (c) { return result.per_competency[c]; }).map(function (c) {
      var s = result.per_competency[c], reach = course.develops[c], lvl = pyRound(reach * Math.min(1, s.accuracy / MASTERY));
      return { competency: c, level: lvl, note: "Passed '" + course.title + "' assessment: " + s.correct + '/' + s.total +
        ' correct on this competency -> ' + lvl + ' (course develops up to ' + reach + '; full credit at ' + Math.round(MASTERY * 100) + '% accuracy).' };
    });
  }
  function stdev(a) { var m = sum(a) / a.length; return Math.sqrt(sum(a.map(function (x) { return (x - m) * (x - m); })) / (a.length - 1)); }
  function labExpected(lab) {
    var cols = lab.dataset.columns, rows = lab.dataset.rows.map(function (r) { var o = {}; cols.forEach(function (c, i) { o[c] = r[i]; }); return o; });
    var wm = sum(rows.map(function (r) { return r.weight * r.consumption; })) / sum(rows.map(function (r) { return r.weight; }));
    var a = rows.filter(function (r) { return r.region === 'A'; }).map(function (r) { return r.consumption; });
    var b = rows.filter(function (r) { return r.region === 'B'; }).map(function (r) { return r.consumption; });
    var ma = sum(a) / a.length, mb = sum(b) / b.length, sa = stdev(a), sb = stdev(b);
    return { weighted_mean: pyRound(wm, 4), se_region_a: pyRound(sa / Math.sqrt(a.length), 4),
      welch_t: pyRound((ma - mb) / Math.sqrt(sa * sa / a.length + sb * sb / b.length), 4) };
  }
  function checkLab(lab, submitted, interp) {
    var exp = labExpected(lab), all = true;
    var tasks = lab.tasks.map(function (t) {
      var raw = String(submitted[t.id] || '').trim().replace(/,/g, ''), v = raw === '' ? NaN : Number(raw);
      var ok = isFinite(v) && Math.abs(v - exp[t.id]) <= t.tolerance; all = all && ok;
      return { id: t.id, label: t.label, submitted: raw, correct: ok, expected: ok ? exp[t.id] : null };
    });
    var textOk = String(interp || '').trim().length >= (lab.min_interpretation_chars || 0);
    return { tasks: tasks, interpretation_ok: textOk, passed: all && textOk };
  }
  function labEvidence(lab, passed) {
    if (!passed) return [];
    return keys(lab.develops).map(function (c) { return { competency: c, level: lab.develops[c], note: "Completed practical lab '" + lab.title + "' with all numeric answers correct." }; });
  }

  root.PWEngine = { computeGaps: computeGaps, goalReadiness: goalReadiness, prerequisiteStatus: prerequisiteStatus,
    scoreCourse: scoreCourse, selectPlan: selectPlan, buildRecommendations: buildRecommendations, buildRoadmap: buildRoadmap,
    topologicalOrder: topologicalOrder, effectiveLevels: effectiveLevels, gradeQuiz: gradeQuiz, remediationPlan: remediationPlan,
    assessmentEvidence: assessmentEvidence, labExpected: labExpected, checkLab: checkLab, labEvidence: labEvidence,
    levelOf: levelOf, basisOf: basisOf, normalizeWeights: normalizeWeights, CONFIDENCE: CONFIDENCE, pyRound: pyRound, CycleError: CycleError };
})(typeof window !== 'undefined' ? window : globalThis);
