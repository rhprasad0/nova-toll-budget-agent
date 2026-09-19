import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["**/node_modules/**", "**/.venv/**", "**/build/**", "**/.worktrees/**", "**/agent/assets/markdown-it.esm.min.mjs", "**/agent/assets/maplibre-gl-6.0.0/maplibre-gl.mjs", "**/agent/assets/maplibre-gl-6.0.0/maplibre-gl-shared.mjs", "**/agent/assets/maplibre-gl-6.0.0/maplibre-gl-worker.mjs", "**/*.d.mts"] },
  js.configs.recommended,
  { linterOptions: { reportUnusedDisableDirectives: "error" } },
  { basePath: import.meta.dirname, files: ["agent/**/*.{js,mjs,cjs}"], ignores: ["agent/public-api-gate.js", "agent/public-report-routes.js"], languageOptions: { globals: globals.browser } },
  {
    basePath: `${import.meta.dirname}/..`,
    files: ["**/*.{js,mjs,cjs}"],
    ignores: ["v2/agent/**"],
    languageOptions: { globals: globals.node },
    rules: {
      // Node tests import browser modules, requiring DOM types in their TS project.
      // Keep browser globals unavailable in Node, including globalThis properties.
      "no-restricted-properties": ["error", ...Object.keys(globals.browser)
        .filter((name) => !(name in globals.node) && !(name in globals.es2022))
        .map((property) => ({ object: "globalThis", property, message: "This browser global is unavailable in Node." }))],
    },
  },
  {
    basePath: import.meta.dirname,
    files: ["tests/cost_dashboard_browser.cjs", "tests/eval_dashboard_browser.cjs"],
    // Playwright serializes these callbacks and executes them in the browser.
    languageOptions: { globals: { document: "readonly", window: "readonly", innerWidth: "readonly" } },
  },
  { basePath: import.meta.dirname, files: ["agent/public-api-gate.js", "agent/public-report-routes.js"], languageOptions: { sourceType: "script" }, rules: { "no-unused-vars": ["error", { varsIgnorePattern: "^handler$" }] } },
];
