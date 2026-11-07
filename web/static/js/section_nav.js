(function () {
  "use strict";

  // On a page that holds nav targets as sections (the home's #radares), the
  // nav link for a section is highlighted while that section is on screen,
  // and the page's own link ("Inicio") the rest of the time. Server-rendered
  // `is-active` still covers every other page.
  function init() {
    var links = Array.prototype.slice.call(document.querySelectorAll(".nav-links a"));
    var pageLink = null;
    var sections = [];

    links.forEach(function (link) {
      var url = new URL(link.href, window.location.href);
      if (url.pathname !== window.location.pathname) return;
      if (!url.hash) {
        pageLink = link;
        return;
      }
      var section = document.getElementById(url.hash.slice(1));
      if (section) sections.push({ link: link, section: section });
    });
    if (!sections.length) return;

    function activate(current) {
      links.forEach(function (link) {
        link.classList.toggle("is-active", link === current);
      });
    }

    function update() {
      // A section counts as current once its top has passed the middle of
      // the viewport, so a short last section still activates at page end.
      var current = pageLink;
      sections.forEach(function (entry) {
        if (entry.section.getBoundingClientRect().top <= window.innerHeight / 2) {
          current = entry.link;
        }
      });
      activate(current);
    }

    // Arriving with (or switching to) a section's hash: the browser is about
    // to scroll there, so highlight it now rather than wait for the scroll.
    function activateFromHash() {
      var match = sections.filter(function (entry) {
        return "#" + entry.section.id === window.location.hash;
      })[0];
      if (match) activate(match.link);
      else update();
    }
    window.addEventListener("hashchange", activateFromHash);

    // After a click, keep the clicked link highlighted through the smooth
    // scroll instead of flickering back to "Inicio" on the way down; resume
    // tracking once scrolling has been idle for a moment.
    var locked = false;
    var unlockTimer = null;
    function lockUntilIdle(delay) {
      locked = true;
      window.clearTimeout(unlockTimer);
      unlockTimer = window.setTimeout(function () {
        locked = false;
        update();
      }, delay);
    }

    var pending = false;
    window.addEventListener("scroll", function () {
      if (locked) {
        lockUntilIdle(150);
        return;
      }
      if (pending) return;
      pending = true;
      window.requestAnimationFrame(function () {
        pending = false;
        update();
      });
    }, { passive: true });

    // Same-page anchor clicks don't reload, so close the mobile menu here.
    var toggle = document.getElementById("nav-toggle");
    sections.forEach(function (entry) {
      entry.link.addEventListener("click", function () {
        if (toggle) toggle.checked = false;
        activate(entry.link);
        lockUntilIdle(1000);
      });
    });

    activateFromHash();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
