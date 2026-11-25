import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:8081",
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    channel: process.env.CI ? undefined : "chrome",
    trace: "on-first-retry",
  },
});
