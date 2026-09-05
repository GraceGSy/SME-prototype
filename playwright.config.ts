import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/viewer",
  outputDir: "./output/playwright/results",
  use: { baseURL: "http://127.0.0.1:8765", headless: true, channel: "msedge" },
  webServer: {
    command: "python tests/viewer_site.py",
    url: "http://127.0.0.1:8765",
    reuseExistingServer: false,
  },
});
