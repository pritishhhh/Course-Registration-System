"use strict";
window.ui = SwaggerUIBundle({
  url: "/openapi.json", dom_id: "#swagger-ui", layout: "BaseLayout",
  deepLinking: true, presets: [SwaggerUIBundle.presets.apis],
  persistAuthorization: false
});
