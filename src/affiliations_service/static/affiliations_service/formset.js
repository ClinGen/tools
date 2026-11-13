// Adds a blank row to a Django formset when staff click its "Add Another" button.
//
// The button's data-formset-add attribute names the formset's prefix. The page holds
// the formset's rows in an element with the ID <prefix>-rows and a blank row in a
// <template> with the ID <prefix>-empty-form, whose names use __prefix__ as the index.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-formset-add]");
  if (!button) {
    return;
  }
  const prefix = button.dataset.formsetAdd;
  const total = document.getElementById(`id_${prefix}-TOTAL_FORMS`);
  const template = document.getElementById(`${prefix}-empty-form`);
  const rows = document.getElementById(`${prefix}-rows`);
  const index = Number(total.value);
  rows.insertAdjacentHTML(
    "beforeend",
    template.innerHTML.replaceAll("__prefix__", String(index)),
  );
  total.value = String(index + 1);
});
