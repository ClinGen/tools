// Adds a Tippy tooltip to every element with a data-tippy-content attribute,
// including elements that HTMX swaps in later. Screen readers already get the
// text from the element's is-sr-only span, so Tippy doesn't add aria-describedby.
htmx.onLoad((element) => {
  tippy(element.querySelectorAll("[data-tippy-content]"), {
    aria: { content: null },
  });
});
