/**
 * Asks for confirmation before submitting any form with a data-confirm attribute.
 * The attribute's value is the question. The modal lives in
 * common/confirm_modal.html, which the base layout includes. The listeners are on
 * the document, so they keep working when HTMX swaps the page body.
 */
(() => {
  let pendingForm = null;
  let pendingSubmitter = null;

  const modal = () => document.getElementById("confirm-modal");

  const close = () => {
    modal()?.classList.remove("is-active");
    pendingForm = null;
    pendingSubmitter = null;
  };

  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.dataset.confirm) return;
      if (form.dataset.confirmed === "true") {
        delete form.dataset.confirmed;
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      pendingForm = form;
      pendingSubmitter = event.submitter;
      document.getElementById("confirm-modal-message").textContent =
        form.dataset.confirm;
      modal().classList.add("is-active");
      document.getElementById("confirm-modal-ok").focus();
    },
    true,
  );

  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    if (event.target.closest("[data-confirm-cancel]")) {
      close();
    } else if (event.target.closest("#confirm-modal-ok") && pendingForm) {
      const form = pendingForm;
      const submitter = pendingSubmitter;
      close();
      form.dataset.confirmed = "true";
      form.requestSubmit(submitter);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal()?.classList.contains("is-active")) {
      close();
    }
  });
})();
