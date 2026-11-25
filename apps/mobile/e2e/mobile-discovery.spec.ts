import { expect, test } from "@playwright/test";

test("mobile Explore, PostGIS filters, EN/HI switch, Branch multi-service slot picker, and Account tab work end-to-end on mobile viewport", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  const serverErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(`pageerror: ${err.message}`));
  page.on("response", (res) => {
    if (res.status() >= 400) {
      serverErrors.push(`http ${res.status()}: ${res.url()}`);
    }
  });

  // 1. Load Explore screen -> displays both [DEMO] branches from live PostGIS API
  await page.goto("/");
  await expect(page.getByText("Verified grooming near you")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("[DEMO] The Brass Comb — Indiranagar")).toBeVisible();
  await expect(page.getByText("[DEMO] The Brass Comb — Bandra West")).toBeVisible();

  // 2. Verify live search input retains focus across typing and filters cleanly
  const searchInput = page.getByPlaceholder("Search salon, street, or service");
  await searchInput.click();
  await searchInput.pressSequentially("Bandra", { delay: 20 });
  await expect(searchInput).toHaveValue("Bandra");
  await expect(searchInput).toBeFocused();
  await expect(page.getByText("[DEMO] The Brass Comb — Bandra West")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("[DEMO] The Brass Comb — Indiranagar")).toHaveCount(0);
  await searchInput.fill("");
  await expect(page.getByText("[DEMO] The Brass Comb — Indiranagar")).toBeVisible({ timeout: 10_000 });

  // 3. Apply Indiranagar PostGIS location preset + Verified filter + sort toggle
  await page.getByText("Indiranagar, BLR").click();
  await page.getByText("Verified only").click();
  await page.getByText("Lowest price").click();
  await expect(page.getByText("[DEMO] The Brass Comb — Indiranagar")).toBeVisible();
  await expect(page.getByText("[DEMO] The Brass Comb — Bandra West")).toHaveCount(0);
  await page.getByText("Lowest price").click();

  // 4. Switch to Hindi and back to EN
  await page.getByText("हिन्दी", { exact: true }).click();
  await expect(page.getByText("आपके पास सत्यापित ग्रूमिंग")).toBeVisible();
  await page.getByText("EN", { exact: true }).click();
  await expect(page.getByText("Verified grooming near you")).toBeVisible();

  // 5. Open Indiranagar branch detail & verify unchecking all services shows empty prompt
  await page.getByText("[DEMO] The Brass Comb — Indiranagar").click();
  await expect(page.getByText("Select services")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("1 services selected")).toBeVisible();

  const beardCheckbox = page.getByRole("checkbox", { name: /Beard Sculpt & Trim \[DEMO\]/ });
  await beardCheckbox.click();
  await expect(
    page.getByText("Select at least one service above to calculate real slot times.")
  ).toBeVisible();

  // Re-check Beard + Haircut ([DEMO], ₹499 + ₹349 = ₹848) and verify >= 48dp target + slots
  await beardCheckbox.click();
  const haircutCheckbox = page.getByRole("checkbox", { name: /Classic Haircut \[DEMO\]/ });
  const box = await haircutCheckbox.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(48);
  await haircutCheckbox.click();
  await expect(page.getByText(/2 services selected/)).toBeVisible();
  await expect(page.getByText(/₹848/)).toBeVisible();

  // Pick Tomorrow if today has no remaining slots late in the day
  const tomorrowMs = Date.now() + 330 * 60 * 1000 + 86_400_000;
  const tomorrowDt = new Date(tomorrowMs);
  const tomorrowIso = tomorrowDt.toISOString().slice(0, 10);
  const tomorrowLabel = new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(`${tomorrowIso}T12:00:00+05:30`));

  const slotButtons = page.getByRole("button").filter({ hasText: /(am|pm|AM|PM)/ });
  if ((await slotButtons.count()) === 0) {
    await page.getByRole("button", { name: tomorrowLabel }).click();
  }
  await expect(slotButtons.first()).toBeVisible({ timeout: 10_000 });
  await slotButtons.first().click();
  await expect(page.getByText(/Selected start time:/)).toBeVisible();

  // 5. Navigate back to Explore and switch to Account tab
  await page.getByText("Back to salons").click();
  await expect(page.getByText("Verified grooming near you")).toBeVisible();
  await page.getByRole("tab", { name: "Account" }).click();
  await expect(page.getByText("Sign in with mobile OTP")).toBeVisible();

  expect(pageErrors).toEqual([]);
  expect(serverErrors).toEqual([]);
});
