(function () {
  "use strict";

  var DURATION_MS = 1400;

  function easeOutExpo(t) {
    return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
  }

  function formatNumber(value, decimals) {
    return value.toLocaleString("es-CO", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  function animate(el) {
    var target = parseFloat(el.dataset.target);
    if (isNaN(target) || el.dataset.animated === "true") return;
    el.dataset.animated = "true";
    var decimals = parseInt(el.dataset.decimals, 10) || 0;

    var start = null;
    function step(timestamp) {
      if (start === null) start = timestamp;
      var progress = Math.min((timestamp - start) / DURATION_MS, 1);
      el.textContent = formatNumber(target * easeOutExpo(progress), decimals);
      if (progress < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  function init() {
    var counters = document.querySelectorAll(".js-counter");
    if (!counters.length) return;

    if (!("IntersectionObserver" in window)) {
      counters.forEach(animate);
      return;
    }

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) animate(entry.target);
        });
      },
      { threshold: 0.4 }
    );
    counters.forEach(function (el) {
      observer.observe(el);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
