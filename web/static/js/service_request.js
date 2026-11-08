(function () {
  "use strict";

  // Opens the detail page's request form (judicial_deposits/_request_form.html)
  // as a modal from the "Quiero recuperarlo" / "Solicitar verificación"
  // buttons, setting the request type. The buttons are real links to
  // ?solicitud=<type>, which the server renders open: this only saves the
  // page reload.
  function init() {
    var dialog = document.getElementById("solicitud");
    if (!dialog || typeof dialog.showModal !== "function") return;
    var typeInput = dialog.querySelector('input[name="request_type"]');
    var title = dialog.querySelector("#jd-request-title");

    function open(type) {
      if (type) {
        typeInput.value = type;
        title.textContent = title.dataset["title" + type.charAt(0).toUpperCase() + type.slice(1)];
      }
      if (dialog.open) dialog.close();
      dialog.showModal();
      var firstError = dialog.querySelector(".jd-field-error");
      var target = firstError
        ? firstError.closest(".jd-field").querySelector("input")
        : dialog.querySelector('input:not([type="hidden"])');
      if (target) target.focus();
    }

    document.querySelectorAll("[data-request-type]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.preventDefault();
        open(button.dataset.requestType);
      });
    });

    dialog.querySelectorAll("[data-request-close]").forEach(function (close) {
      close.addEventListener("click", function (event) {
        event.preventDefault();
        dialog.close();
      });
    });

    // A click on the backdrop (outside the form) closes the modal.
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });

    // Rendered open by the server (validation error, or a no-JS link):
    // reopen it as a real modal.
    if (dialog.hasAttribute("data-open-on-load")) open(null);

    var confirmation = document.getElementById("solicitud-enviada");
    if (confirmation) confirmation.focus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
