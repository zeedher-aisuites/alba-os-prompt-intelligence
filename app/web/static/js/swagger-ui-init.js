"use strict";

window.addEventListener("DOMContentLoaded", () => {
  if (!window.SwaggerUIBundle) {
    return;
  }
  window.SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    presets: [window.SwaggerUIBundle.presets.apis],
    layout: "BaseLayout",
  });
});
