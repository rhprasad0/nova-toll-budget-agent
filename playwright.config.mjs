import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/browser",
  outputDir: "test-results",
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:43992",
    browserName: "chromium"
  },
  webServer: {
    command: "python3 -m http.server 43992 --directory site",
    url: "http://127.0.0.1:43992",
    reuseExistingServer: !process.env.CI
  }
});
