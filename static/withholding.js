// Dividend withholding tax. The settings field, localStorage, and the net
// dividend math all use this. The settings copy states the default: 19%,
// the standard rate in Spain. 0–50 is the range the field and the
// calculation both accept. A typed or stored 60 is kept as 50, and the
// field is rewritten so it cannot show a different number.
//
// The number input in index.html uses the same min, max, and default.
// initSettings applies these constants again when the page loads.

const WITHHOLDING_TAX_DEFAULT = 19;
const WITHHOLDING_TAX_MIN = 0;
const WITHHOLDING_TAX_MAX = 50;
const WITHHOLDING_TAX_STORAGE_KEY = 'dlWithholdingTax';

function normalizeWithholdingTax(value) {
  const parsed = parseInt(value, 10);
  if (!Number.isFinite(parsed)) return WITHHOLDING_TAX_DEFAULT;
  return Math.max(WITHHOLDING_TAX_MIN, Math.min(WITHHOLDING_TAX_MAX, parsed));
}

function readWithholdingTax(storage) {
  const raw = storage.getItem(WITHHOLDING_TAX_STORAGE_KEY);
  const normalized = (raw == null || String(raw).trim() === '')
    ? WITHHOLDING_TAX_DEFAULT
    : normalizeWithholdingTax(raw);
  if (raw !== String(normalized)) {
    storage.setItem(WITHHOLDING_TAX_STORAGE_KEY, String(normalized));
  }
  return normalized;
}

function writeWithholdingTax(value, storage) {
  const normalized = normalizeWithholdingTax(value);
  storage.setItem(WITHHOLDING_TAX_STORAGE_KEY, String(normalized));
  return normalized;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    WITHHOLDING_TAX_DEFAULT,
    WITHHOLDING_TAX_MIN,
    WITHHOLDING_TAX_MAX,
    WITHHOLDING_TAX_STORAGE_KEY,
    normalizeWithholdingTax,
    readWithholdingTax,
    writeWithholdingTax,
  };
}
