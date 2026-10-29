/* Plugin Dashboard page. Reads status.json and history.json written by the collector.
   All repository data is inserted with textContent, never innerHTML. */
(function () {
  'use strict';

  var LABELS = {red: 'Needs fixing', amber: 'Needs attention', green: 'Healthy', grey: 'Not checked'};
  var ORDER = ['red', 'amber', 'green', 'grey'];
  var state = {filter: 'all', query: '', status: null, history: {}, view: 'list'};
  var VIEWS = [['list', 'List'], ['todo', 'To do'], ['releases', 'Releases'], ['grid', 'Grid']];
  var LEVEL_RANK = {ok: 0, info: 1, amber: 2, red: 3};
  /* Columns of the Grid view: each groups related checks. */
  var GRID_GROUPS = [
    ['CI', ['ci_status', 'ci_activity', 'ci_setup']],
    ['Release', ['release_match', 'release_zip', 'unreleased']],
    ['Moodle', ['moodle_support', 'moodle_baseline']],
    ['Licence', ['licence', 'licence_mode', 'repo_files']],
    ['Strings & JS', ['lang_strings', 'amd_build']],
    ['Directory', ['plugins_directory']],
    ['Security', ['security_alerts']],
    ['Issues', ['issues']],
    ['Upkeep', ['dormant_actions']]
  ];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function store(key, value) {
    try {
      if (value === undefined) { return window.localStorage.getItem(key); }
      window.localStorage.setItem(key, value);
    } catch (e) { /* Storage blocked: filters just won't be remembered. */ }
    return null;
  }

  function formatter(tz, withTime) {
    var opts = {day: '2-digit', month: '2-digit', year: 'numeric'};
    if (withTime) { opts.hour = '2-digit'; opts.minute = '2-digit'; opts.hour12 = false; }
    try { opts.timeZone = tz; return new Intl.DateTimeFormat('en-AU', opts); } catch (e) {
      delete opts.timeZone; return new Intl.DateTimeFormat('en-AU', opts);
    }
  }

  function safeUrl(url) {
    return typeof url === 'string' && /^https?:\/\//i.test(url) ? url : null;
  }

  function link(text, url) {
    var href = safeUrl(url);
    if (!href) { return el('span', null, text); }
    var a = el('a', null, text);
    a.href = href;
    a.rel = 'noopener noreferrer';
    a.target = '_blank';
    return a;
  }

  /* Reversible, so two repos can never share an id: letters, digits and '-' are kept, any other
     character (including '_') becomes _<hex code>_. The result is still a valid CSS identifier. */
  function slug(name) {
    return 'repo-' + name.replace(/[^A-Za-z0-9-]/g, function (c) { return '_' + c.charCodeAt(0).toString(16) + '_'; });
  }

  function relativeAge(iso) {
    var days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    if (days <= 0) { return 'today'; }
    if (days === 1) { return 'yesterday'; }
    return days + ' days ago';
  }

  /* Grey covers two different cases; name the real one for a repo. */
  function stateLabel(repo) {
    if (repo.status === 'grey') { return repo.archived ? 'Archived' : 'Unreadable'; }
    return LABELS[repo.status];
  }

  function renderHeader() {
    var s = state.status;
    var tz = s.timezone || 'UTC';
    var when = s.run && s.run.finished_at ? formatter(tz, true).format(new Date(s.run.finished_at)) : 'never';
    var parts = ['Checked ' + when + ' (' + tz + ')'];
    if (s.moodle && s.moodle.latest_label) { parts.push('newest Moodle: ' + s.moodle.latest_label); }
    document.getElementById('checked').textContent = parts.join(', ');

    var banner = document.getElementById('banner');
    if (s.run && !s.run.ok) {
      banner.hidden = false;
      banner.textContent = 'The last check failed, so this page shows the previous results. Reason: ' +
        (s.run.error || 'unknown') + '. Fix it in the YunoHost config panel, then use Run now.';
    } else if (s.run && s.run.error) {
      banner.hidden = false;
      banner.textContent = 'Some sources could not be read: ' + s.run.error;
    } else {
      banner.hidden = true;
    }

    var rack = document.getElementById('rack');
    rack.textContent = '';
    s.repos.forEach(function (repo) {
      var a = el('a', repo.status);
      a.href = '#' + slug(repo.full_name);
      a.title = (repo.component || repo.name) + ': ' + stateLabel(repo) + '. ' + repo.summary;
      a.setAttribute('aria-label', (repo.component || repo.name) + ', ' + stateLabel(repo));
      a.addEventListener('click', function () { openRow(repo.full_name); });
      rack.appendChild(a);
    });
  }

  function renderSegments() {
    var seg = document.getElementById('segments');
    seg.textContent = '';
    var counts = state.status.counts || {};
    var items = [{key: 'all', label: 'All', count: state.status.repos.length}];
    ORDER.forEach(function (key) {
      if (counts[key]) { items.push({key: key, label: LABELS[key], count: counts[key]}); }
    });
    items.forEach(function (item) {
      var b = el('button');
      b.type = 'button';
      b.setAttribute('aria-pressed', String(state.filter === item.key));
      if (item.key !== 'all') { b.appendChild(el('span', 'dot ' + item.key)); }
      b.appendChild(el('span', 'count', String(item.count)));
      b.appendChild(el('span', null, item.label));
      b.addEventListener('click', function () {
        state.filter = item.key;
        store('plugindash.filter', item.key);
        renderSegments();
        renderList();
      });
      seg.appendChild(b);
    });
  }

  function ticks(repo) {
    var wrap = el('span', 'ticks');
    var days = state.history[repo.full_name] || [];
    // day.date is already the local day (YYYY-MM-DD), so format it in UTC: no second conversion.
    var fmt = formatter('UTC', false);
    var padding = Math.max(0, 30 - days.length);
    for (var i = 0; i < padding; i++) { wrap.appendChild(el('i')); }
    days.slice(-30).forEach(function (day) {
      var t = el('i', day.status);
      t.title = fmt.format(new Date(day.date + 'T12:00:00Z')) + ': ' + LABELS[day.status];
      wrap.appendChild(t);
    });
    wrap.setAttribute('title', 'Last 30 days, oldest on the left');
    return wrap;
  }

  function buildRow(repo) {
    var tpl = document.getElementById('row-template');
    var row = tpl.content.firstElementChild.cloneNode(true);
    row.classList.add(repo.status);
    row.id = slug(repo.full_name);
    // The component is the plugin's Moodle identity; the repo name is secondary.
    row.querySelector('.name').textContent = repo.component || repo.name;
    row.querySelector('.component').textContent = repo.name;
    var mode = row.querySelector('.mode');
    if (repo.mode) {
      mode.textContent = repo.mode;
      mode.classList.add(repo.mode === 'SCCA' ? 'mode-a' : (repo.mode === 'GPL' ? 'mode-b' : 'mode-other'));
      mode.title = 'Licence mode, from the @license tag in version.php';
    } else {
      mode.hidden = true;
    }
    row.querySelector('.summary').textContent = repo.summary;
    row.querySelector('.tag').textContent = repo.archived ? '' : (repo.latest_tag || 'no release');
    row.querySelector('.range').textContent = repo.supported ? 'Moodle ' + repo.supported[0] + '–' + repo.supported[1] : '';
    row.querySelector('.state').textContent = stateLabel(repo);
    row.querySelector('.ticks').replaceWith(ticks(repo));

    var list = row.querySelector('.findings');
    repo.findings.forEach(function (f) {
      var li = el('li', f.level);
      li.appendChild(el('span', 'dot ' + (f.level === 'red' || f.level === 'amber' ? f.level : '')));
      var text = el('span');
      text.appendChild(f.url ? link(f.message, f.url) : el('span', null, f.message));
      text.appendChild(el('span', 'check', f.check));
      if (f.fix) { text.appendChild(el('span', 'fix', 'What to do: ' + f.fix)); }
      li.appendChild(text);
      list.appendChild(li);
    });

    var links = row.querySelector('.links');
    links.appendChild(link('Repository', repo.url));
    if (repo.latest_tag_url) { links.appendChild(link('Release ' + repo.latest_tag, repo.latest_tag_url)); }
    if (repo.pushed_at) { links.appendChild(el('span', null, 'Last push ' + relativeAge(repo.pushed_at))); }
    if (repo.private) { links.appendChild(el('span', null, 'Private')); }
    if (repo.fork) { links.appendChild(el('span', null, 'Fork')); }

    var head = row.querySelector('.row-head');
    var detail = row.querySelector('.detail');
    head.addEventListener('click', function () {
      var open = head.getAttribute('aria-expanded') === 'true';
      head.setAttribute('aria-expanded', String(!open));
      detail.hidden = open;
    });
    return row;
  }

  function matches(repo) {
    if (state.filter !== 'all' && repo.status !== state.filter) { return false; }
    if (!state.query) { return true; }
    var q = state.query.toLowerCase();
    return [repo.full_name, repo.component || '', repo.summary, repo.mode || ''].some(function (v) {
      return v.toLowerCase().indexOf(q) !== -1;
    });
  }

  function renderViews() {
    var bar = document.getElementById('views');
    bar.textContent = '';
    VIEWS.forEach(function (v) {
      var b = el('button', 'view', v[1]);
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(state.view === v[0]));
      b.addEventListener('click', function () {
        state.view = v[0];
        store('plugindash.view', v[0]);
        renderViews();
        renderList();
      });
      bar.appendChild(b);
    });
  }

  function checkTitle(id) {
    var found = (state.status.checks || []).filter(function (c) { return c.id === id; })[0];
    return found ? found.title : id;
  }

  /* A plugin name that opens that plugin in the List view. */
  function plugin(repo) {
    var b = el('button', 'plugin-link', repo.component || repo.name);
    b.type = 'button';
    b.addEventListener('click', function () {
      state.view = 'list';
      store('plugindash.view', 'list');
      renderViews();
      openRow(repo.full_name);
    });
    return b;
  }

  function problems(repo) {
    return repo.findings.filter(function (f) { return f.level === 'red' || f.level === 'amber'; });
  }

  /* To do: problems grouped by check, worst and most widespread first, with what to do. */
  function renderTodo(board, shown) {
    var groups = {};
    shown.forEach(function (repo) {
      problems(repo).forEach(function (f) { (groups[f.check] = groups[f.check] || []).push([repo, f]); });
    });
    var ids = Object.keys(groups).sort(function (a, b) {
      var worst = function (id) { return Math.max.apply(null, groups[id].map(function (x) { return LEVEL_RANK[x[1].level]; })); };
      return worst(b) - worst(a) || groups[b].length - groups[a].length || a.localeCompare(b);
    });
    if (!ids.length) { board.appendChild(el('p', 'board-note', 'Nothing to do: no problems in the plugins shown.')); }
    ids.forEach(function (id) {
      var items = groups[id];
      var red = items.some(function (x) { return x[1].level === 'red'; });
      var card = el('section', 'todo ' + (red ? 'red' : 'amber'));
      var head = el('h2');
      head.appendChild(el('span', 'pill ' + (red ? 'red' : 'amber'), red ? 'Needs fixing' : 'Needs attention'));
      head.appendChild(el('span', null, checkTitle(id) + ' · ' + items.length + ' plugin' + (items.length === 1 ? '' : 's')));
      card.appendChild(head);
      var fixes = items.map(function (x) { return x[1].fix; }).filter(Boolean);
      var shared = fixes.length === items.length && fixes.every(function (f) { return f === fixes[0]; });
      if (shared) { card.appendChild(el('p', 'todo-fix', 'What to do: ' + fixes[0])); }
      var ul = el('ul');
      items.forEach(function (x) {
        var li = el('li');
        li.appendChild(plugin(x[0]));
        var text = el('span', 'todo-msg');
        text.appendChild(x[1].url ? link(x[1].message, x[1].url) : el('span', null, x[1].message));
        if (!shared && x[1].fix) { text.appendChild(el('span', 'fix', 'What to do: ' + x[1].fix)); }
        li.appendChild(text);
        ul.appendChild(li);
      });
      card.appendChild(ul);
      board.appendChild(card);
    });
  }

  function finding(repo, id) {
    return repo.findings.filter(function (f) { return f.check === id; })[0];
  }

  /* One table cell: text, a level for its colour, and the finding's message as a tooltip. */
  function cell(text, level, title) {
    var td = el('td', level ? 'lv-' + level : null, text);
    if (title) { td.title = title; }
    return td;
  }

  /* Releases: where each plugin's release stands, from version.php to moodle.org. */
  function renderReleases(board, shown) {
    var table = el('table', 'grid-table');
    var head = el('tr');
    ['Plugin', 'version.php', 'Latest tag', 'Tag matches', 'Zip', 'Unreleased', 'moodle.org', 'Moodle'].forEach(function (h) {
      head.appendChild(el('th', null, h));
    });
    table.appendChild(head);
    shown.forEach(function (repo) {
      var tr = el('tr');
      var name = el('td');
      name.appendChild(plugin(repo));
      if (repo.mode) { name.appendChild(el('span', 'sub', repo.mode)); }
      tr.appendChild(name);
      tr.appendChild(cell(repo.release || '—'));
      tr.appendChild(cell(repo.latest_tag || 'none', repo.latest_tag ? null : 'info'));
      var m = finding(repo, 'release_match');
      tr.appendChild(m && m.level !== 'info' ? cell(m.level === 'ok' ? '✓' : '✗ mismatch', m.level, m.message) : cell('—'));
      var z = finding(repo, 'release_zip');
      var zip = '—';
      if (z) {
        zip = z.level === 'ok' ? '✓ attached' : z.message.indexOf('not needed') !== -1 ? 'not needed' :
          z.message.indexOf('no zip') !== -1 ? '✗ missing' : 'misnamed';
      }
      tr.appendChild(cell(zip, z ? z.level : null, z ? z.message : null));
      var u = finding(repo, 'unreleased');
      var unreleased = '—';
      if (u) {
        var bumped = /^version\.php says (\S+)/.exec(u.message);
        var commits = /^(\d+ commits?)/.exec(u.message);
        unreleased = u.level === 'ok' ? 'none' : bumped ? bumped[1] + ' not published' : commits ? commits[1] : u.message;
      }
      tr.appendChild(cell(unreleased, u ? u.level : null, u ? u.message : null));
      var d = finding(repo, 'plugins_directory');
      var listed = '—';
      if (d) {
        var behind = /^Directory has ([^;]+);/.exec(d.message);
        var as = /^Listed as (.+)$/.exec(d.message);
        listed = d.level === 'red' ? '✗ listed (in-house)' : /^Not in the public/.test(d.message) ? 'not listed (in-house)' :
          behind ? 'behind (' + behind[1] + ')' : /^Directory is up to date/.test(d.message) ? '✓ up to date' :
          /^Not listed/.test(d.message) ? 'not listed' : as ? 'listed (' + as[1] + ')' : 'unknown';
      }
      tr.appendChild(cell(listed, d ? d.level : null, d ? d.message : null));
      tr.appendChild(cell(repo.supported ? repo.supported[0] + '–' + repo.supported[1] : '—'));
      table.appendChild(tr);
    });
    var wrap = el('div', 'table-wrap');
    wrap.appendChild(table);
    board.appendChild(wrap);
  }

  /* Grid: every plugin against each group of checks, as one coloured dot per group. */
  function renderGrid(board, shown) {
    var table = el('table', 'grid-table grid-dots');
    var head = el('tr');
    head.appendChild(el('th', null, 'Plugin'));
    GRID_GROUPS.forEach(function (g) { head.appendChild(el('th', 'c', g[0])); });
    table.appendChild(head);
    shown.forEach(function (repo) {
      var tr = el('tr');
      var name = el('td');
      name.appendChild(plugin(repo));
      name.appendChild(el('span', 'sub', (repo.mode ? repo.mode + ' · ' : '') + (repo.latest_tag || 'no release')));
      tr.appendChild(name);
      GRID_GROUPS.forEach(function (g) {
        var found = repo.findings.filter(function (f) { return g[1].indexOf(f.check) !== -1; });
        var td = el('td', 'c');
        var worst = found.reduce(function (a, f) { return LEVEL_RANK[f.level] > LEVEL_RANK[a] ? f.level : a; }, 'ok');
        var dot = el('span', 'dot ' + (!found.length ? 'none' : worst === 'red' || worst === 'amber' ? worst : 'green'));
        dot.title = found.length ? found.map(function (f) { return f.message; }).join('\n') : 'Not checked';
        dot.setAttribute('aria-label', g[0] + ': ' + (!found.length ? 'not checked' : worst));
        td.appendChild(dot);
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    var wrap = el('div', 'table-wrap');
    wrap.appendChild(table);
    board.appendChild(wrap);
  }

  function renderList() {
    var list = document.getElementById('list');
    var board = document.getElementById('board');
    var empty = document.getElementById('empty');
    list.textContent = '';
    board.textContent = '';
    var shown = state.status.repos.filter(matches);
    list.hidden = state.view !== 'list';
    board.hidden = state.view === 'list';
    if (state.view === 'list') {
      shown.forEach(function (repo) { list.appendChild(buildRow(repo)); });
    } else if (shown.length) {
      var live = shown.filter(function (r) { return !r.archived; });
      ({todo: renderTodo, releases: renderReleases, grid: renderGrid})[state.view](board, live);
    }
    if (!state.status.repos.length) {
      empty.hidden = false;
      empty.textContent = 'No Moodle plugins found yet. Add a GitHub token in the YunoHost config panel, ' +
        'then use Run now.';
    } else if (!shown.length) {
      empty.hidden = false;
      empty.textContent = 'No plugins match. Clear the search or choose All.';
    } else {
      empty.hidden = true;
    }
  }

  function renderAbout() {
    var dl = document.getElementById('checks');
    dl.textContent = '';
    (state.status.checks || []).forEach(function (c) {
      dl.appendChild(el('dt', null, c.title));
      var dd = el('dd', null, c.description + (c.override ? ' (Level changed to ' + c.override + ' in settings.)' : ''));
      dl.appendChild(dd);
    });
    var run = state.status.run || {};
    document.getElementById('fineprint').textContent = 'Plugin Dashboard ' + (state.status.app_version || '') +
      '. Last run took ' + (run.duration_s || 0) + ' s and made ' + (run.api_calls || 0) + ' API calls.';
  }

  function openRow(fullName) {
    state.filter = 'all';
    state.query = '';
    document.getElementById('search').value = '';
    renderSegments();
    renderList();
    var row = document.getElementById(slug(fullName));
    if (row) {
      var head = row.querySelector('.row-head');
      head.setAttribute('aria-expanded', 'true');
      row.querySelector('.detail').hidden = false;
      head.focus({preventScroll: true});
    }
  }

  /* The plugins currently shown, so an export matches the filter and search on screen. */
  function shownRepos() {
    return state.status ? state.status.repos.filter(matches) : [];
  }

  function dateStamp() {
    var d = new Date();
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function csvCell(value) {
    var text = value === null || value === undefined ? '' : String(value);
    return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function downloadFile(name, type, text) {
    var blob = new Blob([text], {type: type});
    var url = URL.createObjectURL(blob);
    var a = el('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function exportCsv() {
    var headers = ['Repository', 'Component', 'Licence mode', 'Status', 'Summary', 'Release',
      'Supported Moodle', 'Open issues', 'Open PRs', 'Last push', 'URL'];
    var lines = [headers.map(csvCell).join(',')];
    shownRepos().forEach(function (repo) {
      lines.push([
        repo.full_name,
        repo.component || repo.name,
        repo.mode || '',
        stateLabel(repo),
        repo.summary,
        repo.archived ? '' : (repo.latest_tag || 'no release'),
        repo.supported ? repo.supported[0] + '–' + repo.supported[1] : '',
        repo.open_issues,
        repo.open_prs,
        repo.pushed_at || '',
        repo.url
      ].map(csvCell).join(','));
    });
    // A BOM (﻿) so Excel reads the UTF-8 (accented names) correctly.
    downloadFile('plugin-dashboard-' + dateStamp() + '.csv', 'text/csv;charset=utf-8',
      '﻿' + lines.join('\r\n') + '\r\n');
  }

  function exportPdf() {
    // The print stylesheet expands every row's findings, so just open the print dialog
    // (where the browser offers "Save as PDF"). The on-screen view is left untouched.
    window.print();
  }

  function runStatus(text) {
    var node = document.getElementById('run-status');
    if (node) { node.textContent = text || ''; }
  }

  function render() {
    renderViews();
    renderHeader();
    renderSegments();
    renderList();
    renderAbout();
    setExportsEnabled((state.status.repos || []).length > 0);
  }

  /* After starting a check, wait for a newer run to land, then redraw the page. */
  function pollForRun(baseline, deadline, button) {
    window.setTimeout(function () {
      load('status.json').then(function (status) {
        if (((status.run && status.run.finished_ts) || 0) > baseline) {
          return load('history.json').catch(function () { return {}; }).then(function (history) {
            state.status = status;
            state.history = history || {};
            if (state.filter !== 'all' && !(status.counts || {})[state.filter]) { state.filter = 'all'; }
            render();
            runStatus(status.run && status.run.ok ? 'Updated just now.'
              : 'Check finished with a problem — see the banner above.');
            button.disabled = false;
          });
        }
        if (Date.now() > deadline) {
          runStatus('Still running — reload the page in a little while.');
          button.disabled = false;
          return;
        }
        pollForRun(baseline, deadline, button);
      }).catch(function () {
        if (Date.now() > deadline) {
          runStatus('Reload the page to see the results.');
          button.disabled = false;
          return;
        }
        pollForRun(baseline, deadline, button);
      });
    }, 4000);
  }

  function runNow() {
    var button = document.getElementById('run-now');
    if (button.disabled) { return; }
    button.disabled = true;
    runStatus('Starting a check…');
    // Read the current run time straight from disk first: if a scheduled check finished
    // while this page sat open, the displayed status is stale and would be mistaken for
    // the run we're about to start.
    load('status.json').then(function (status) {
      return (status.run && status.run.finished_ts) || 0;
    }).catch(function () {
      return (state.status && state.status.run && state.status.run.finished_ts) || 0;
    }).then(function (baseline) {
      return fetch('run', {method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'}})
        .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)); })
        .then(function (data) {
          runStatus(data && data.started === false && data.running
            ? 'A check is already running…' : 'Checking… this takes a minute or two.');
          pollForRun(baseline, Date.now() + 6 * 60 * 1000, button);
        });
    }).catch(function () {
      runStatus('Couldn’t start a check here. Use the YunoHost config panel.');
      button.disabled = false;
    });
  }

  function load(url) {
    return fetch(url, {cache: 'no-store', credentials: 'same-origin'}).then(function (r) {
      if (!r.ok) { throw new Error(url + ' returned ' + r.status); }
      return r.json();
    });
  }

  function setExportsEnabled(enabled) {
    ['export-csv', 'export-pdf'].forEach(function (id) {
      document.getElementById(id).disabled = !enabled;
    });
  }

  function start() {
    state.filter = store('plugindash.filter') || 'all';
    var saved = store('plugindash.view');
    state.view = VIEWS.some(function (v) { return v[0] === saved; }) ? saved : 'list';
    document.getElementById('search').addEventListener('input', function (e) {
      state.query = e.target.value.trim();
      renderList();
    });
    setExportsEnabled(false);
    document.getElementById('export-csv').addEventListener('click', exportCsv);
    document.getElementById('export-pdf').addEventListener('click', exportPdf);
    document.getElementById('run-now').addEventListener('click', runNow);
    load('status.json').then(function (status) {
      state.status = status;
      if (state.filter !== 'all' && !(status.counts || {})[state.filter]) { state.filter = 'all'; }
      return load('history.json').catch(function () { return {}; });
    }).then(function (history) {
      state.history = history || {};
      render();
      if (location.hash) {
        var row = document.querySelector(location.hash.replace(/[^#A-Za-z0-9_-]/g, ''));
        if (row) { row.scrollIntoView(); }
      }
    }).catch(function () {
      document.getElementById('checked').textContent = 'No results yet.';
      var empty = document.getElementById('empty');
      empty.hidden = false;
      empty.textContent = 'The first check hasn’t run yet. In YunoHost, open this app’s config panel, ' +
        'add your GitHub token, then use Run now.';
    });
  }

  start();
}());
