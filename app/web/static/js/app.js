"use strict";

// One-click demo briefs for the workflow creation form. The briefs reuse
// already-seeded projects, so they only work after scripts/demo.sh (or the
// manual seed steps) has run. Target platform and generation method are left
// blank on purpose: setting them would filter out the seeded evidence.
const DEMO_BRIEFS = {
  approve: {
    projectSlug: "retrieval-evaluation-lab",
    queryType: "ai_influencer",
    brief:
      "Create a cobalt-dressed virtual host in a premium lounge; preserve the same face, cobalt wardrobe, and shoulder-length dark hairstyle.",
    constraints: ["Preserve the same face", "Keep the approved cobalt outfit"],
  },
  revise: {
    projectSlug: "retrieval-evaluation-lab",
    queryType: "video_frame",
    brief:
      "Continue the two travelers crossing a modern station in sequential frames, keeping their wardrobe, screen position, and left-to-right movement.",
    constraints: ["Keep left-to-right movement", "Keep wardrobe unchanged between frames"],
  },
  reject: {
    projectSlug: "cobalt-lounge",
    queryType: "logo",
    brief:
      "Design a geometric Alba monogram from two cobalt arcs on white, with perfect symmetry.",
    constraints: ["Keep perfect symmetry", "Use only cobalt on white"],
  },
};

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-constraint]");
  if (button) {
    button.closest(".constraint-input")?.remove();
    return;
  }
  const demoButton = event.target.closest("[data-demo]");
  if (demoButton) {
    fillDemoBrief(demoButton.dataset.demo);
  }
});

function fillDemoBrief(name) {
  const demo = DEMO_BRIEFS[name];
  if (!demo) {
    return;
  }
  const form = document.querySelector("form[action$='/workflows']");
  if (!form) {
    return;
  }
  const projectSelect = form.querySelector("#project_id");
  const projectOption = projectSelect?.querySelector(`option[data-slug="${demo.projectSlug}"]`);
  if (!projectOption) {
    alert(`Demo project "${demo.projectSlug}" is not seeded yet. Run scripts/demo.sh first.`);
    return;
  }
  projectSelect.value = projectOption.value;
  const queryTypeSelect = form.querySelector("#query_type");
  if (queryTypeSelect) {
    queryTypeSelect.value = demo.queryType;
  }
  const briefField = form.querySelector("#brief");
  if (briefField) {
    briefField.value = demo.brief;
  }
  const constraintsContainer = form.querySelector("#constraints");
  if (constraintsContainer) {
    constraintsContainer.innerHTML = "";
    for (const constraint of demo.constraints) {
      const wrapper = document.createElement("div");
      wrapper.className = "constraint-input";
      const label = document.createElement("label");
      label.className = "sr-only";
      label.textContent = "Constraint";
      const input = document.createElement("input");
      input.name = "constraints";
      input.maxLength = 500;
      input.value = constraint;
      input.placeholder = "Describe a constraint";
      const remove = document.createElement("button");
      remove.className = "button icon";
      remove.type = "button";
      remove.setAttribute("data-remove-constraint", "");
      remove.setAttribute("aria-label", "Remove constraint");
      remove.textContent = "Remove";
      wrapper.append(label, input, remove);
      constraintsContainer.append(wrapper);
    }
  }
  const providerSelect = form.querySelector("#provider");
  if (providerSelect) {
    providerSelect.value = "fake";
  }
  briefField?.focus();
}


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
