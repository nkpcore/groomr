import assert from "node:assert/strict";
import test from "node:test";

import {
  formatINRFromPaise,
  getTranslations,
  I18N_DICTIONARIES,
  isValidOtpCode,
  normalizePhoneE164,
} from "../src/index.js";

test("formatINRFromPaise formats whole and fractional rupees cleanly", () => {
  assert.equal(formatINRFromPaise(0), "₹0");
  assert.equal(formatINRFromPaise(49900), "₹499");
  assert.equal(formatINRFromPaise(99900), "₹999");
  assert.equal(formatINRFromPaise(12550), "₹125.50");
  assert.equal(formatINRFromPaise(10000000), "₹1,00,000");
});

test("formatINRFromPaise rejects non-integer paise", () => {
  assert.throws(() => formatINRFromPaise(499.5), RangeError);
});

test("normalizePhoneE164 and isValidOtpCode validate Indian mobile numbers cleanly", () => {
  assert.equal(normalizePhoneE164("9876543210"), "+919876543210");
  assert.equal(normalizePhoneE164("+91 90000 00003"), "+919000000003");
  assert.equal(normalizePhoneE164("919000000001"), "+919000000001");
  assert.equal(normalizePhoneE164("12345"), null);
  assert.equal(isValidOtpCode("123456"), true);
  assert.equal(isValidOtpCode("012345"), true);
  assert.equal(isValidOtpCode("12345"), false);
});

test("en and hi dictionaries share identical top-level and nested keys", () => {
  const en = getTranslations("en");
  const hi = getTranslations("hi");
  assert.deepEqual(Object.keys(en), Object.keys(hi));
  for (const section of Object.keys(en) as Array<keyof typeof I18N_DICTIONARIES.en>) {
    assert.deepEqual(Object.keys(en[section]), Object.keys(hi[section]));
  }
});
