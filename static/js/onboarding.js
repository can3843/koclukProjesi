/* Rotam onboarding: sliders and per-subject auto save. Pages work without JS (plain form posts). */
(function () {
  "use strict";

  var HEAVY_MINUTES = 540;

  function formatDuration(minutes) {
    var hours = Math.floor(minutes / 60);
    var rest = minutes % 60;
    var parts = [];
    if (hours) parts.push(hours + " saat");
    if (rest || !hours) parts.push(rest + " dakika");
    return parts.join(" ");
  }

  /* ---------- Step 2: time sliders ---------- */
  var timeForm = document.getElementById("time-form");
  if (timeForm) {
    var weekdays = parseInt(timeForm.dataset.weekdays, 10) || 0;
    var weekends = parseInt(timeForm.dataset.weekends, 10) || 0;
    var weekdayInput = timeForm.querySelector("[name=weekday_minutes]");
    var weekendInput = timeForm.querySelector("[name=weekend_minutes]");
    var warning = timeForm.querySelector("[data-heavy-warning]");
    var total = timeForm.querySelector("[data-total]");

    var update = function () {
      var wd = parseInt(weekdayInput.value, 10);
      var we = parseInt(weekendInput.value, 10);
      timeForm.querySelector('[data-out="weekday_minutes"]').textContent = formatDuration(wd);
      timeForm.querySelector('[data-out="weekend_minutes"]').textContent = formatDuration(we);
      total.textContent = Math.round((weekdays * wd + weekends * we) / 60);
      warning.hidden = !(wd > HEAVY_MINUTES || we > HEAVY_MINUTES);
    };
    [weekdayInput, weekendInput].forEach(function (el) { el.addEventListener("input", update); });
    update();
  }

  /* ---------- Step 4: levels, saved subject by subject ---------- */
  document.documentElement.classList.add("js");

  function updateMarked(form, marked) {
    var box = form.closest("[data-subject-box]");
    var counter = box && box.querySelector("[data-marked]");
    if (counter) counter.textContent = marked;
  }

  function countMarked(form) {
    var marked = 0;
    form.querySelectorAll(".topic-row").forEach(function (row) {
      var checked = row.querySelector("input[type=radio]:checked");
      if (checked && checked.value !== "0") marked += 1;
    });
    return marked;
  }

  function save(form) {
    var data = new URLSearchParams(new FormData(form));
    return fetch(form.action || window.location.href, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "X-CSRFToken": window.rotam ? window.rotam.csrfToken() : "",
      },
      body: data.toString(),
    }).then(function (response) {
      if (!response.ok) throw new Error("save failed");
      return response.json();
    });
  }

  function saveWithToast(form) {
    save(form).catch(function () {
      if (window.rotam) window.rotam.toast("Kaydedilemedi, tekrar dene.", "error");
    });
  }

  document.querySelectorAll("[data-levels-form]").forEach(function (form) {
    form.addEventListener("change", function (event) {
      if (event.target.type !== "radio") return;
      updateMarked(form, countMarked(form));
      saveWithToast(form);
    });

    form.querySelectorAll("button[name=set_all]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.preventDefault();
        var value = button.value;
        form.querySelectorAll(".topic-row input[type=radio]").forEach(function (radio) {
          radio.checked = radio.value === value;
        });
        updateMarked(form, value === "0" ? 0 : form.querySelectorAll(".topic-row").length);
        saveWithToast(form);
      });
    });

    form.addEventListener("submit", function (event) { event.preventDefault(); });
  });
})();
