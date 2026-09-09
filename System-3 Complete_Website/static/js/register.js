/* Shared register flow: modal open/close + POST to /api/register.
   On success, registration ALWAYS routes through login next (per spec). */
(function () {
  var modal = document.getElementById('registerModal');
  if (!modal) return;

  var errBox = document.getElementById('regError');
  var form = document.getElementById('registerForm');

  function open() { errBox.style.display = 'none'; modal.classList.add('active'); }
  function close() { modal.classList.remove('active'); }
  function onKey(e) { if (e.key === 'Escape') close(); }

  Array.prototype.forEach.call(document.querySelectorAll('[data-open-modal]'), function (el) {
    el.addEventListener('click', open);
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-close-modal], #closeRegister'), function (el) {
    el.addEventListener('click', close);
  });
  modal.addEventListener('click', function (e) { if (e.target === modal) close(); });
  document.addEventListener('keydown', onKey);

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    errBox.style.display = 'none';
    var username = document.getElementById('regUsername').value.trim();
    var password = document.getElementById('regPassword').value;
    if (!username || !password) {
      errBox.textContent = 'Please fill in both username and password.';
      errBox.style.display = 'block';
      return;
    }
    fetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username, password: password })
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, data: d }; });
    }).then(function (res) {
      if (res.ok) {
        // Successful registration always routes through login.
        window.location.href = '/login';
      } else {
        errBox.textContent = res.data.error || 'Registration failed. Please try again.';
        errBox.style.display = 'block';
      }
    }).catch(function () {
      errBox.textContent = 'Could not reach the server. Please try again.';
      errBox.style.display = 'block';
    });
  });
})();
