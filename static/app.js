(function () {
  var burger = document.querySelector('.burger'), menu = document.querySelector('.menu');
  if (burger) burger.addEventListener('click', function () {
    var o = menu.classList.toggle('open'); burger.setAttribute('aria-expanded', o);
  });

  // Optimistic-free upvote via fetch; falls back to normal form post
  document.addEventListener('submit', function (ev) {
    var f = ev.target;
    if (!f.classList.contains('vote-form')) return;
    ev.preventDefault();
    var b = f.querySelector('.vote');
    fetch(f.action, { method: 'POST', headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return { s: r.status, j: j }; }); })
      .then(function (x) {
        if (x.s === 401) { location.href = '/login'; return; }
        b.classList.toggle('on', x.j.voted); b.setAttribute('aria-pressed', x.j.voted);
        b.querySelector('b').textContent = x.j.count;
      })
      .catch(function () { f.submit(); });
  });

  // AI autofill on the launch form
  var btn = document.getElementById('ai-btn');
  if (!btn) return;
  var note = document.getElementById('ai-note');
  var $ = function (id) { return document.getElementById(id); };
  btn.addEventListener('click', function () {
    var url = $('f-url').value.trim();
    if (!/^https?:\/\//.test(url)) { note.textContent = 'Enter a full URL starting with https:// first.'; return; }
    btn.disabled = true; var old = btn.innerHTML; btn.innerHTML = '<span class="spin"></span>Reading your site…';
    note.textContent = '';
    fetch('/api/ai/launch-copy', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ url: url, notes: ($('f-description').value || '') })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        if (!x.ok) { note.textContent = x.j.error || 'Something went wrong.'; return; }
        var d = x.j;
        $('f-name').value = d.name || ''; $('f-tagline').value = (d.tagline || '').slice(0, 60);
        $('f-description').value = d.description || '';
        if (d.category) $('f-category').value = d.category;
        $('f-features').value = (d.features || []).join('\n');
        note.textContent = (d.mode === 'ai' ? '✨ Drafted with AI. ' : '') + (d.note || 'Review and edit before publishing.') +
          (d.first_comment ? ' Suggested first comment: "' + d.first_comment + '"' : '');
      })
      .catch(function () { note.textContent = 'Network error. Try again.'; })
      .then(function () { btn.disabled = false; btn.innerHTML = old; });
  });
})();
