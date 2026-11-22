(function () {
  "use strict";

  // The detail page's deposit preview (judicial_deposits/_deposit_preview.html).
  // Without this script the table simply stays open and the toggle stays
  // hidden; with it, the table starts closed behind "Ver más detalles".
  function init() {
    document.querySelectorAll("[data-jd-more]").forEach(function (block) {
      var toggle = block.querySelector("[data-jd-more-toggle]");
      var body = block.querySelector("[data-jd-more-body]");
      if (!toggle || !body) return;

      function set(open) {
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        body.hidden = !open;
      }

      set(false);
      toggle.hidden = false;
      toggle.addEventListener("click", function () {
        set(toggle.getAttribute("aria-expanded") !== "true");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
