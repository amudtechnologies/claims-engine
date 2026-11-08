(function () {
  "use strict";

  // Nav links that point to a section of the current page (the home's
  // #radares) don't reload it, so close the mobile menu on click. The
  // highlighted link is the server-rendered `is-active` ("Inicio" anywhere on
  // the home page) and doesn't follow the scroll.
  function init() {
    var toggle = document.getElementById("nav-toggle");
    if (!toggle) return;
    Array.prototype.slice.call(document.querySelectorAll(".nav-links a")).forEach(function (link) {
      var url = new URL(link.href, window.location.href);
      if (url.pathname !== window.location.pathname || !url.hash) return;
      link.addEventListener("click", function () {
        toggle.checked = false;
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
