/* Rotam: CSRF helper, toasts, theme switcher. Progressive enhancement only. */
(function () {
  "use strict";

  var rotam = (window.rotam = window.rotam || {});

  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  rotam.csrfToken = function () {
    return getCookie("csrftoken");
  };

  rotam.postJSON = function (url, data) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "X-CSRFToken": rotam.csrfToken(),
      },
      body: new URLSearchParams(data || {}).toString(),
    }).then(function (response) {
      return response.json();
    });
  };

  /* ---------- Toasts ---------- */

  var TOAST_MS = 4000;

  function dismissToast(el) {
    el.classList.add("is-leaving");
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 300);
  }

  rotam.toast = function (message, type) {
    var host = document.getElementById("toasts");
    if (!host) return;
    var el = document.createElement("div");
    el.className = "toast" + (type ? " " + type : "");
    el.setAttribute("role", type === "error" ? "alert" : "status");
    el.textContent = message;
    host.appendChild(el);
    setTimeout(function () { dismissToast(el); }, TOAST_MS);
  };

  document.querySelectorAll("#toasts .toast").forEach(function (el) {
    setTimeout(function () { dismissToast(el); }, TOAST_MS);
  });

  /* ---------- Theme ---------- */

  var THEME_KEY = "rotam-theme";
  var root = document.documentElement;

  function storedTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }

  function currentTheme() {
    var explicit = root.getAttribute("data-theme");
    if (explicit) return explicit;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  rotam.setTheme = function (theme) {
    root.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* storage unavailable */ }
  };

  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      rotam.setTheme(currentTheme() === "dark" ? "light" : "dark");
    });
  });

  if (storedTheme()) root.setAttribute("data-theme", storedTheme());
  root.classList.add("js");

  /* Settings page: choose light, dark or "follow the device" (no stored choice). */
  var themeChoices = document.querySelectorAll("[data-theme-choice]");

  function markThemeChoice() {
    var saved = storedTheme() || "system";
    themeChoices.forEach(function (btn) {
      var active = btn.dataset.themeChoice === saved;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  themeChoices.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var choice = btn.dataset.themeChoice;
      if (choice === "system") {
        root.removeAttribute("data-theme");
        try { localStorage.removeItem(THEME_KEY); } catch (e) { /* storage unavailable */ }
      } else {
        rotam.setTheme(choice);
      }
      markThemeChoice();
    });
  });
  if (themeChoices.length) markThemeChoice();

  /* ---------- Top bar: blur and bottom line once the page is scrolled ---------- */

  var topbar = document.querySelector("[data-topbar]");
  if (topbar) {
    var onScroll = function () { topbar.dataset.scrolled = String(window.scrollY > 8); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ---------- Forms: show/hide password, Caps Lock hint, loading state on submit ---------- */

  function svgIcon(name) {
    return '<svg class="icon" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  }

  document.querySelectorAll(".field input[type=password]").forEach(function (input) {
    var wrap = document.createElement("div");
    wrap.className = "pw-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "icon-btn pw-toggle";
    toggle.setAttribute("aria-label", "Parolayı göster");
    toggle.setAttribute("aria-pressed", "false");
    toggle.innerHTML = svgIcon("eye");
    wrap.appendChild(toggle);
    toggle.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      toggle.setAttribute("aria-pressed", String(show));
      toggle.setAttribute("aria-label", show ? "Parolayı gizle" : "Parolayı göster");
      toggle.innerHTML = svgIcon(show ? "eye-off" : "eye");
    });

    var hint = document.createElement("p");
    hint.className = "caps-hint";
    hint.hidden = true;
    hint.innerHTML = svgIcon("alert") + "Caps Lock açık";
    wrap.after(hint);
    var check = function (event) {
      if (event.getModifierState) hint.hidden = !event.getModifierState("CapsLock");
    };
    input.addEventListener("keydown", check);
    input.addEventListener("keyup", check);
    input.addEventListener("blur", function () { hint.hidden = true; });
  });

  document.querySelectorAll("[data-auth-form]").forEach(function (form) {
    var button = form.querySelector("button[type=submit]");
    form.addEventListener("submit", function () {
      if (button) button.dataset.loading = "true";
    });
    // coming back with the browser's back button must not leave the button stuck
    window.addEventListener("pageshow", function () { if (button) delete button.dataset.loading; });
  });

  /* ---------- Tasks (today screen): mark done / skip / undo without a page reload ---------- */

  var taskList = document.querySelector("[data-task-list]");
  var summaryBox = document.querySelector("[data-day-summary]");
  var RING_LENGTH = 213.63;

  function setText(selector, value) {
    var el = document.querySelector(selector);
    if (el) el.textContent = value;
  }

  function setRing(percent) {
    var ring = document.querySelector("[data-ring-value]");
    if (!ring) return;
    ring.setAttribute("stroke-dashoffset", (RING_LENGTH * (1 - percent / 100)).toFixed(2));
    setText("[data-ring-text]", "%" + percent);
    var svg = document.querySelector("[data-ring]");
    if (svg) svg.setAttribute("aria-label", "Bugünün ilerlemesi %" + percent);
  }

  function updateSummary(day, streak) {
    if (!summaryBox) return;
    var percent = day.planned_minutes ? Math.round((100 * day.done_minutes) / day.planned_minutes) : 0;
    setText("[data-done-count]", day.done_count);
    setText("[data-total-count]", day.total_count);
    setText("[data-done-minutes]", day.done_minutes);
    setText("[data-planned-minutes]", day.planned_minutes);
    setText("[data-streak]", streak);
    setRing(percent);
  }

  function confetti() {
    var colors = ["#6A63EE", "#B9B6FF", "#FF8A5C", "#3FB68B", "#F2B84B"];
    var holder = document.createElement("div");
    holder.className = "confetti";
    holder.setAttribute("aria-hidden", "true");
    for (var i = 0; i < 28; i++) {
      var piece = document.createElement("span");
      piece.style.left = Math.round(Math.random() * 100) + "%";
      piece.style.background = colors[i % colors.length];
      piece.style.animationDelay = (Math.random() * 0.6).toFixed(2) + "s";
      holder.appendChild(piece);
    }
    document.body.appendChild(holder);
    setTimeout(function () { if (holder.parentNode) holder.parentNode.removeChild(holder); }, 3200);
  }

  function showCelebration(allDone, wasAllDone) {
    var box = document.querySelector("[data-celebrate]");
    if (box) box.hidden = !allDone;
    if (allDone && !wasAllDone) confetti();
  }

  if (taskList) {
    setRing(parseInt((document.querySelector("[data-ring-value]") || { dataset: {} }).dataset.percent || "0", 10));

    // the circle of a practice/review task first opens the optional D/Y/B fields
    taskList.addEventListener("click", function (event) {
      var check = event.target.closest("[data-check]");
      if (!check) return;
      var card = check.closest("[data-task]");
      var details = card && card.querySelector("[data-dyb]");
      if (details && !details.open) {
        event.preventDefault();
        details.open = true;
        var first = details.querySelector("input");
        if (first) first.focus();
      }
    });

    taskList.addEventListener("submit", function (event) {
      var form = event.target.closest("[data-task-form]");
      if (!form) return;
      event.preventDefault();
      var card = form.closest("[data-task]");
      var data = new URLSearchParams(new FormData(form));
      if (event.submitter && event.submitter.name) data.set(event.submitter.name, event.submitter.value);
      var wasAllDone = !document.querySelector("[data-celebrate]").hidden;
      card.classList.add("is-busy");

      fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "Accept": "application/json",
          "X-CSRFToken": rotam.csrfToken(),
        },
        body: data.toString(),
      })
        .then(function (response) { return response.json(); })
        .then(function (body) {
          card.classList.remove("is-busy");
          if (!body.ok) {
            rotam.toast(body.error || "Bir sorun oluştu, tekrar dene.", "error");
            return;
          }
          var holder = document.createElement("div");
          holder.innerHTML = body.html.trim();
          var fresh = holder.firstElementChild;
          card.replaceWith(fresh);
          if (body.task.status !== "pending" && rotam.timer) rotam.timer.taskChanged(body.task.id);
          if (body.task.status === "done") fresh.classList.add("just-done");
          updateSummary(body.day, body.streak);
          rotam.toast(body.message, "success");
          showCelebration(body.day.total_count > 0 && body.day.done_count === body.day.total_count, wasAllDone);
        })
        .catch(function () {
          card.classList.remove("is-busy");
          rotam.toast("Bağlantı sorunu, tekrar dene.", "error");
        });
    });
  }
})();
