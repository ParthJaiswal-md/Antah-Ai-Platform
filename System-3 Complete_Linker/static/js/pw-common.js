/* AntahAI Learning Pathways - shared browser helpers (no dependencies). */
(function () {
  'use strict';
  var meta = document.querySelector('meta[name="csrf-token"]');
  var CSRF = meta ? meta.getAttribute('content') : '';

  function api(method, url, body, isForm) {
    var opts = { method: method, headers: { 'X-CSRF-Token': CSRF }, credentials: 'same-origin' };
    if (body !== undefined && body !== null) {
      if (isForm) { opts.body = body; }
      else { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: 'Unexpected server response (' + r.status + ').' }; })
        .then(function (data) {
          if (!r.ok || data.ok === false) {
            var err = new Error(data.error || ('Request failed (' + r.status + ').'));
            err.status = r.status; throw err;
          }
          return data;
        });
    }, function () { throw new Error('Could not reach the server. Check your connection.'); });
  }

  var toastEl;
  function toast(msg, isErr) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast'; toastEl.setAttribute('role', 'status');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.toggle('err', !!isErr);
    toastEl.classList.add('show');
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(function () { toastEl.classList.remove('show'); }, 3200);
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var P = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  var ICONS = {
    check: '<svg viewBox="0 0 24 24" ' + P + '><path d="M5 12.5l4.2 4.2L19 7"/></svg>',
    lock: '<svg viewBox="0 0 24 24" ' + P + '><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 118 0v3"/></svg>',
    play: '<svg viewBox="0 0 24 24" ' + P + '><path d="M8 5.5v13l10.5-6.5z"/></svg>',
    clock: '<svg viewBox="0 0 24 24" ' + P + '><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
    half: '<svg viewBox="0 0 24 24" ' + P + '><circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 010 17z" fill="currentColor"/></svg>',
    ban: '<svg viewBox="0 0 24 24" ' + P + '><circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/></svg>',
    quiz: '<svg viewBox="0 0 24 24" ' + P + '><path d="M9 9a3 3 0 115 2.2c-.9.6-2 1.2-2 2.8"/><circle cx="12" cy="17.5" r=".6" fill="currentColor"/><circle cx="12" cy="12" r="9"/></svg>',
    lab: '<svg viewBox="0 0 24 24" ' + P + '><path d="M9 3h6M10 3v6.5L4.8 18.2A2 2 0 006.5 21h11a2 2 0 001.7-2.8L14 9.5V3"/><path d="M7.5 15h9"/></svg>',
    flag: '<svg viewBox="0 0 24 24" ' + P + '><path d="M5 21V4M5 4h11l-2 4 2 4H5"/></svg>',
    book: '<svg viewBox="0 0 24 24" ' + P + '><path d="M4 5.5A2.5 2.5 0 016.5 3H20v15H6.5A2.5 2.5 0 004 20.5z"/><path d="M4 20.5A2.5 2.5 0 016.5 18H20v3H6.5"/></svg>',
    plus: '<svg viewBox="0 0 24 24" ' + P + '><path d="M12 5v14M5 12h14"/></svg>',
    minus: '<svg viewBox="0 0 24 24" ' + P + '><path d="M5 12h14"/></svg>',
    fit: '<svg viewBox="0 0 24 24" ' + P + '><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
    reset: '<svg viewBox="0 0 24 24" ' + P + '><path d="M4 12a8 8 0 108-8 8.2 8.2 0 00-5.7 2.3L4 8.5"/><path d="M4 4v4.5h4.5"/></svg>',
    close: '<svg viewBox="0 0 24 24" ' + P + '><path d="M6 6l12 12M18 6L6 18"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" ' + P + '><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    analyst: '<svg viewBox="0 0 24 24" ' + P + '><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
    viz: '<svg viewBox="0 0 24 24" ' + P + '><path d="M3 17l5-6 4 3 6-8 3 3"/><path d="M3 21h18"/></svg>',
    survey: '<svg viewBox="0 0 24 24" ' + P + '><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/></svg>',
    applied: '<svg viewBox="0 0 24 24" ' + P + '><circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5M8.5 11h5M11 8.5v5"/></svg>'
  };

  window.PW = { api: api, toast: toast, esc: esc, icons: ICONS, csrf: CSRF };
})();
