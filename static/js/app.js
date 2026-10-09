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
})();
