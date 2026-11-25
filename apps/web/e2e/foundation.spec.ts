import { expect, test } from "@playwright/test";

test("foundation routes render live API health and EN/HI switching without console or HTTP errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      errors.push(`console: ${msg.text()}`);
    }
  });
  page.on("response", (res) => {
    if (res.status() >= 400) {
      errors.push(`http ${res.status()}: ${res.url()}`);
    }
  });

  for (const path of ["/", "/partner", "/admin"]) {
    await page.goto(path);
    await expect(page.getByText("All Core Services Ready")).toBeVisible();
    await expect(page.getByText("CHAIR VERIFIED")).toBeVisible();
  }

  await page.goto("/");
  await page.getByRole("button", { name: "हिन्दी" }).click();
  await expect(page.getByText("सभी मुख्य सेवाएं तैयार हैं")).toBeVisible();

  expect(errors).toEqual([]);
});
