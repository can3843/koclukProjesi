/* Rotam Pomodoro timer (today screen). Counts focus time on one task and sends it to the server.
   Progressive enhancement: without JS the "Odaklan" buttons stay hidden and nothing else changes. */
(function () {
  "use strict";

  var panel = document.querySelector("[data-timer]");
  if (!panel) return;

  var rotam = (window.rotam = window.rotam || {});
  var KEY = "rotam-timer";
  var SLEEP_GAP = 120; // seconds: a longer gap between two ticks means the device slept, so the timer pauses
  var cfg = {
    focus: parseInt(panel.dataset.focus, 10),
    pause: parseInt(panel.dataset["break"], 10),
    longPause: parseInt(panel.dataset.longBreak, 10),
    cycles: parseInt(panel.dataset.cycles, 10),
    flush: parseInt(panel.dataset.flush, 10),
  };
  var urlTemplate = panel.dataset.urlTemplate;
  var els = {
    phase: panel.querySelector("[data-timer-phase]"),
    task: panel.querySelector("[data-timer-task]"),
    clock: panel.querySelector("[data-timer-clock]"),
    cycle: panel.querySelector("[data-timer-cycle]"),
    toggle: panel.querySelector("[data-timer-toggle]"),
    skip: panel.querySelector("[data-timer-skip]"),
    finish: panel.querySelector("[data-timer-finish]"),
  };
  var baseTitle = document.title;
  var state = null;
  var ticker = null;
  var lastFlush = 0;

  /* ---------- storage ---------- */

  function save() {
    try {
      if (state) localStorage.setItem(KEY, JSON.stringify(state));
      else localStorage.removeItem(KEY);
    } catch (e) { /* storage unavailable: the timer still works until the page closes */ }
  }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  /* ---------- sending time to the server ---------- */

  function formatMinutes(seconds) {
    var minutes = Math.floor(seconds / 60);
    var hours = Math.floor(minutes / 60);
    var rest = minutes % 60;
    if (hours && rest) return hours + " sa " + rest + " dk";
    return hours ? hours + " sa" : rest + " dk";
  }

  function showSaved(body) {
    var card = document.querySelector('[data-task][data-task-id="' + body.task.id + '"]');
    var label = card && card.querySelector("[data-focus-label]");
    if (label) label.textContent = body.task.focus_seconds >= 60 ? " · " + formatMinutes(body.task.focus_seconds) + " odak" : "";
    var total = document.querySelector("[data-focus-total]");
    if (total && body.day) total.textContent = formatMinutes(body.day.focus_seconds);
  }

  function flush(taskId, keepalive) {
    if (!state || state.taskId !== taskId || state.pending < 1) return Promise.resolve();
    var seconds = state.pending;
    state.pending = 0;
    save();
    lastFlush = Date.now();
    return fetch(urlTemplate.replace(/0\/sure\/$/, taskId + "/sure/"), {
      method: "POST",
      credentials: "same-origin",
      keepalive: !!keepalive,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "X-CSRFToken": rotam.csrfToken ? rotam.csrfToken() : "",
      },
      body: new URLSearchParams({ seconds: String(seconds) }).toString(),
    })
      .then(function (response) {
        return response.json().then(function (body) { return { status: response.status, body: body }; });
      })
      .then(function (result) {
        if (result.body.ok) {
          showSaved(result.body);
        } else if (result.status >= 500 && state && state.taskId === taskId) {
          state.pending += seconds; // try again with the next flush
          save();
        } // 4xx: the task cannot take time any more (done a long time ago, skipped...): drop it
      })
      .catch(function () {
        if (state && state.taskId === taskId) {
          state.pending += seconds;
          save();
        }
      });
  }

  /* ---------- rendering ---------- */

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function render() {
    if (!state) {
      panel.hidden = true;
      document.body.classList.remove("has-timer");
      document.title = baseTitle;
      return;
    }
    panel.hidden = false;
    document.body.classList.add("has-timer");
    var minutes = Math.floor(state.remaining / 60);
    var clock = pad(minutes) + ":" + pad(state.remaining % 60);
    var isFocus = state.phase === "focus";
    els.clock.textContent = clock;
    els.phase.textContent = isFocus ? "Odak" : state.phase === "long" ? "Uzun mola" : "Mola";
    panel.classList.toggle("is-break", !isFocus);
    els.task.textContent = state.title;
    els.cycle.textContent = state.cycles ? "Tamamlanan odak turu: " + state.cycles : "İlk odak turun";
    els.toggle.textContent = state.running ? "Duraklat" : isFocus && state.remaining === cfg.focus && !state.started ? "Başlat" : "Devam";
    els.skip.hidden = isFocus;
    document.title = state.running ? clock + " · " + els.phase.textContent + " — rotam" : baseTitle;
  }

  /* ---------- clock ---------- */

  function beep() {
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      var ctx = new Ctx();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.value = 0.08;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.25);
      setTimeout(function () { ctx.close(); }, 400);
    } catch (e) { /* no sound is fine */ }
    if (navigator.vibrate) { try { navigator.vibrate(200); } catch (e) { /* ignore */ } }
  }

  function startTicker() {
    if (ticker) return;
    ticker = setInterval(tick, 1000);
  }

  function stopTicker() {
    if (ticker) clearInterval(ticker);
    ticker = null;
  }

  function endPhase() {
    var taskId = state.taskId;
    if (state.phase === "focus") {
      state.cycles += 1;
      var long = state.cycles % cfg.cycles === 0;
      state.phase = long ? "long" : "break";
      state.remaining = long ? cfg.longPause : cfg.pause;
      state.running = true; // the break starts by itself
      state.lastTick = Date.now();
      rotam.toast && rotam.toast("Odak turu bitti, mola zamanı!", "success");
    } else {
      state.phase = "focus";
      state.remaining = cfg.focus;
      state.running = false; // the next focus waits for the student
      state.started = false;
      stopTicker();
      rotam.toast && rotam.toast("Mola bitti. Hazır olunca devam et.", "success");
    }
    beep();
    save();
    render();
    flush(taskId);
  }

  function tick() {
    if (!state || !state.running) { stopTicker(); return; }
    var now = Date.now();
    var delta = Math.floor((now - state.lastTick) / 1000);
    if (delta <= 0) return;
    state.lastTick += delta * 1000;
    if (delta > SLEEP_GAP) { // the device slept: do not count that time
      pause();
      return;
    }
    delta = Math.min(delta, state.remaining);
    state.remaining -= delta;
    if (state.phase === "focus") state.pending += delta;
    if (state.remaining <= 0) {
      endPhase();
      return;
    }
    save();
    render();
    if (state.phase === "focus" && Date.now() - lastFlush > cfg.flush * 1000) flush(state.taskId);
  }

  function resume() {
    state.running = true;
    state.started = true;
    state.lastTick = Date.now();
    save();
    startTicker();
    render();
  }

  function pause() {
    if (!state) return;
    state.running = false;
    stopTicker();
    save();
    render();
    flush(state.taskId);
  }

  function finish() {
    if (!state) return Promise.resolve();
    var taskId = state.taskId;
    stopTicker();
    state.running = false;
    return flush(taskId).then(function () {
      state = null;
      save();
      render();
    });
  }

  function begin(taskId, title) {
    var previous = state ? finish() : Promise.resolve();
    previous.then(function () {
      state = {
        taskId: taskId, title: title, phase: "focus", remaining: cfg.focus, cycles: 0,
        pending: 0, running: false, started: false, lastTick: Date.now(),
      };
      lastFlush = Date.now();
      resume();
    });
  }

  /* ---------- events ---------- */

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-focus-start]");
    if (!button) return;
    var card = button.closest("[data-task]");
    begin(card.dataset.taskId, button.dataset.title || "Görev");
  });

  els.toggle.addEventListener("click", function () {
    if (!state) return;
    if (state.running) pause(); else resume();
  });

  els.skip.addEventListener("click", function () {
    if (!state || state.phase === "focus") return;
    state.phase = "focus";
    state.remaining = cfg.focus;
    state.running = false;
    state.started = false;
    stopTicker();
    save();
    render();
  });

  els.finish.addEventListener("click", function () { finish(); });

  window.addEventListener("pagehide", function () {
    if (!state) return;
    state.running = false; // time while the page is closed is not counted
    save();
    flush(state.taskId, true);
  });

  /* app.js tells us when a task was completed, skipped or undone */
  rotam.timer = {
    taskChanged: function (taskId) {
      if (state && String(state.taskId) === String(taskId)) finish();
    },
  };

  /* ---------- restore after a page load ---------- */

  state = load();
  if (state) {
    var card = document.querySelector('[data-task][data-task-id="' + state.taskId + '"]');
    if (!card || !card.classList.contains("is-pending")) {
      var stale = state.taskId;
      flush(stale).then(function () { state = null; save(); render(); });
    } else {
      state.running = false; // restored paused: the student decides when to continue
      render();
      flush(state.taskId);
    }
  }
  render();
})();
