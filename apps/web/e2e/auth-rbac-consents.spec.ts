import { expect, test } from "@playwright/test";

test("customer can authenticate via phone OTP, persist DPDP consents, see permission-denied on admin/partner, and partner/admin surfaces enforce RBAC", async ({
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

  // 1. Customer OTP Sign-In on /
  await page.goto("/");
  await page.getByLabel("Mobile number").fill("+919000000003");
  await page.getByRole("button", { name: "Send verification code" }).click();
  await expect(page.getByText("Use verification code 123456")).toBeVisible();

  await page.getByLabel("6-digit SMS code").fill("123456");
  await page.getByRole("button", { name: "Verify and sign in" }).click();

  await expect(page.getByText("Assigned roles: CUSTOMER")).toBeVisible();

  // 2. DPDP Consent save & reload persistence
  const termsCheckbox = page.getByLabel(/Terms of Service/i);
  const dpdpCheckbox = page.getByLabel(/DPDP Privacy Processing/i);
  if (!(await termsCheckbox.isChecked())) {
    await termsCheckbox.check();
  }
  if (!(await dpdpCheckbox.isChecked())) {
    await dpdpCheckbox.check();
  }
  await page.getByRole("button", { name: "Save privacy preferences" }).click();
  await expect(page.getByText("Privacy preferences saved and recorded in audit trail.")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel(/Terms of Service/i)).toBeChecked();
  await expect(page.getByLabel(/DPDP Privacy Processing/i)).toBeChecked();

  // 3. Customer encounters explicit permission-denied on /partner and /admin
  await page.goto("/partner");
  await expect(page.getByText("You do not have permission to view this surface.")).toBeVisible();
  await page.goto("/admin");
  await expect(page.getByText("You do not have permission to view this surface.")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in with mobile OTP" })).toBeVisible();

  // 4. Partner owner signs in on /partner and verifies scoped branches
  await page.goto("/partner");
  await page.getByLabel("Mobile number").fill("+919000000001");
  await page.getByRole("button", { name: "Send verification code" }).click();
  await page.getByLabel("6-digit SMS code").fill("123456");
  await page.getByRole("button", { name: "Verify and sign in" }).click();

  await expect(page.getByText("[DEMO] The Brass Comb — Indiranagar")).toBeVisible();
  await page.getByRole("button", { name: "Verify branch access" }).first().click();
  await expect(page.getByText("Branch scope confirmed").first()).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();

  // 5. Admin signs in on /admin and inspects audit logs table
  await page.goto("/admin");
  await page.getByLabel("Mobile number").fill("+919000000002");
  await page.getByRole("button", { name: "Send verification code" }).click();
  await page.getByLabel("6-digit SMS code").fill("123456");
  await page.getByRole("button", { name: "Verify and sign in" }).click();

  await expect(page.getByRole("heading", { name: "Security & consent audit trail" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "USER_LOGIN" }).first()).toBeVisible();

  expect(pageErrors).toEqual([]);
  expect(server5xx).toEqual([]);
});
