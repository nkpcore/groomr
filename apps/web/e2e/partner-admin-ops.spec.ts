import { expect, test } from "@playwright/test";

const VALID_TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
  "base64"
);

test("partner can onboard salon, configure desk/walk-in/KYC signed files, and admin enforces hygiene safety override", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  const server5xx: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));
  page.on("response", (res) => {
    if (res.status() >= 500) {
      server5xx.push(`${res.status()} ${res.url()}`);
    }
  });

  const tag = Date.now().toString().slice(-6);
  const brandName = `[DEMO] E2E Salon ${tag}`;
  const branchName = `[DEMO] E2E Branch ${tag}`;

  // 1. Partner signs in on /partner
  await page.goto("/partner");
  await page.getByLabel("Mobile number").fill("+919000000001");
  await page.getByRole("button", { name: "Send verification code" }).click();
  await page.getByLabel("6-digit SMS code").fill("123456");
  await page.getByRole("button", { name: "Verify and sign in" }).click();

  await expect(page.getByText("[DEMO] The Brass Comb — Indiranagar")).toBeVisible();

  // 2. Register a brand-new salon & branch under Onboarding & KYC tab
  await page.getByRole("tab", { name: "Onboarding & KYC" }).click();
  await page.getByLabel("Legal entity name").fill(`${brandName} Pvt Ltd`);
  await page.getByLabel("Brand display name").fill(brandName);
  await page.getByLabel("Branch name").fill(branchName);
  await page.getByLabel("Street address").fill("77 CMH Road");
  await page.getByLabel("City").fill("Bengaluru");
  await page.getByLabel("State").fill("Karnataka");
  await page.getByLabel("PIN code").fill("560038");
  await page.getByRole("button", { name: "Register salon & branch" }).click();

  await expect(page.getByText(branchName).first()).toBeVisible();

  // 3. Upload valid PNG KYC document and inspect signed preview dialog
  await page.getByLabel(/Select PNG, JPG, WebP, or PDF/i).setInputFiles({
    name: "shop-license.png",
    mimeType: "image/png",
    buffer: VALID_TINY_PNG,
  });
  await page.getByRole("button", { name: "Upload private document" }).click();
  await expect(page.getByRole("button", { name: "Open signed preview" }).first()).toBeVisible();

  await page.getByRole("button", { name: "Open signed preview" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // 4. Configure barber & shifts in Shop Setup so walk-in seating can allocate staff + chair
  await page.getByRole("tab", { name: "Shop Setup" }).click();
  await page.getByRole("textbox", { name: "Barber name" }).fill("Arjun E2E");
  await page.getByRole("button", { name: "Add barber & shifts" }).click();
  await expect(page.locator("span", { hasText: "Arjun E2E" }).first()).toBeVisible();

  // 5. Add and seat walk-in on Live Desk for the newly created branch
  await page.getByRole("tab", { name: "Live Desk" }).click();
  await page.getByLabel("Guest name").fill("Rohan E2E");
  await page.getByLabel("Service summary").fill("Beard Sculpt");
  await page.getByRole("button", { name: "Check in walk-in" }).click();
  await expect(page.getByText(/#1 Rohan E2E/)).toBeVisible();
  await page.getByRole("button", { name: "Seat" }).first().click();
  await page.getByRole("button", { name: "Start" }).first().click();
  await page.getByRole("button", { name: "Complete" }).first().click();

  // Sign out of partner session
  await page.getByRole("button", { name: "Sign out" }).click();

  // 5. Admin signs in on /admin and verifies KYC + critical hygiene override
  await page.goto("/admin");
  await page.getByLabel("Mobile number").fill("+919000000002");
  await page.getByRole("button", { name: "Send verification code" }).click();
  await page.getByLabel("6-digit SMS code").fill("123456");
  await page.getByRole("button", { name: "Verify and sign in" }).click();

  const branchHeading = page.getByRole("heading", { name: `${brandName} — ${branchName}` });
  await expect(branchHeading).toBeVisible();
  const branchCard = page.locator("article").filter({ has: branchHeading });

  // Inspect signed file as admin and approve document
  await branchCard.getByRole("button", { name: "Inspect signed file" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  await branchCard.getByRole("button", { name: "Approve doc" }).first().click();
  await expect(branchCard.getByText("APPROVED")).toBeVisible();

  // Record inspection with score 98 but UNCHECK critical single-use blade control -> FAILED_CRITICAL
  await branchCard.getByLabel("Inspection score (0–100)").fill("98");
  await branchCard.getByLabel("Fresh single-use razor blades enforced").uncheck();
  await branchCard.getByRole("button", { name: "Record inspection" }).click();
  await expect(branchCard.getByText(/FAILED_CRITICAL · Score 98\/100/)).toBeVisible();
  await expect(branchCard.getByText(/Status: SUSPENDED · Badge: SUSPENDED/)).toBeVisible();

  // Re-inspect with all critical items checked and score 92 -> PASSED + CHAIR_VERIFIED
  await branchCard.getByLabel("Fresh single-use razor blades enforced").check();
  await branchCard.getByLabel("Inspection score (0–100)").fill("92");
  await branchCard.getByRole("button", { name: "Record inspection" }).click();
  await expect(branchCard.getByText(/PASSED · Score 92\/100/)).toBeVisible();
  await expect(branchCard.getByText(/Status: ACTIVE · Badge: CHAIR_VERIFIED/)).toBeVisible();

  expect(pageErrors).toEqual([]);
  expect(server5xx).toEqual([]);
});
