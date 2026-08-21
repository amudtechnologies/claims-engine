(function () {
  "use strict";

  function init() {
    var rows = document.querySelectorAll("[data-row-href]");
    rows.forEach(function (row) {
      row.addEventListener("click", function (event) {
        if (event.target.closest("a")) return;
        window.location.href = row.dataset.rowHref;
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
