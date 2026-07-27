"use strict";

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-constraint]");
  if (button) {
    button.closest(".constraint-input")?.remove();
  }
});

document.body.addEventListener("htmx:beforeRequest", (event) => {
  const form = event.detail.elt.closest("form");
  form?.querySelectorAll("button[type='submit']").forEach((button) => {
    button.disabled = true;
  });
});

document.body.addEventListener("htmx:afterRequest", (event) => {
  const form = event.detail.elt.closest("form");
  form?.querySelectorAll("button[type='submit']").forEach((button) => {
    button.disabled = false;
  });
});
