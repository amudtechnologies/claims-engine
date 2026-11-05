(function () {
  "use strict";

  // Visual progress for the (server-rendered) lookup: the form still submits
  // normally; this only shows that work is under way and guards double submits.
  document.querySelectorAll("[data-search-form]").forEach(function (form) {
    var status = form.querySelector("[data-search-status]");
    var button = form.querySelector("button[type=submit]");

    form.addEventListener("submit", function () {
      if (!form.checkValidity() || form.classList.contains("is-loading")) return;
      form.classList.add("is-loading");
      button.setAttribute("aria-busy", "true");
      if (status) status.textContent = "Consultando…";
    });
  });

  // Back/forward cache restores the page in its loading state.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.querySelectorAll("[data-search-form].is-loading").forEach(function (form) {
      form.classList.remove("is-loading");
      var button = form.querySelector("button[type=submit]");
      if (button) button.removeAttribute("aria-busy");
    });
  });
})();
