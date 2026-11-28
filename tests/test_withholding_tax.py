"""Withholding tax is one number for the field and the dividend math.

Run: python tests/test_withholding_tax.py

The settings box, localStorage, and the net-dividend rate all go through
static/withholding.js. A stored or typed 60 is kept as 50. A missing value
is 19, the rate named in the settings copy.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run():
    script = r"""
const {
  WITHHOLDING_TAX_DEFAULT,
  WITHHOLDING_TAX_MIN,
  WITHHOLDING_TAX_MAX,
  WITHHOLDING_TAX_STORAGE_KEY,
  normalizeWithholdingTax,
  readWithholdingTax,
  writeWithholdingTax,
} = require("./static/withholding.js");

function store(initial) {
  const data = Object.assign({}, initial || {});
  return {
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null;
    },
    setItem(key, value) { data[key] = String(value); },
    snapshot() { return Object.assign({}, data); },
  };
}

function net(gross, rate) {
  return gross * (1 - rate / 100);
}

const key = WITHHOLDING_TAX_STORAGE_KEY;
const out = {
  defaultRate: WITHHOLDING_TAX_DEFAULT,
  min: WITHHOLDING_TAX_MIN,
  max: WITHHOLDING_TAX_MAX,
  normalize: {
    missing: normalizeWithholdingTax(""),
    junk: normalizeWithholdingTax("nope"),
    zero: normalizeWithholdingTax("0"),
    spain: normalizeWithholdingTax("19"),
    fraction: normalizeWithholdingTax("19.6"),
    negative: normalizeWithholdingTax("-4"),
    cap: normalizeWithholdingTax("50"),
    over: normalizeWithholdingTax("60"),
    wayOver: normalizeWithholdingTax("100"),
  },
};

const fresh = store();
out.fresh = { rate: readWithholdingTax(fresh), saved: fresh.snapshot()[key] };

const kept = store({ [key]: "19" });
out.kept = { rate: readWithholdingTax(kept), saved: kept.snapshot()[key] };

const legacy = store({ [key]: "60" });
const legacyRate = readWithholdingTax(legacy);
out.legacy = {
  rate: legacyRate,
  saved: legacy.snapshot()[key],
  netOn100: net(100, legacyRate),
};

const typed = store({ [key]: "19" });
const typedRate = writeWithholdingTax("60", typed);
out.typed = {
  rate: typedRate,
  saved: typed.snapshot()[key],
  shown: String(typedRate),
  netOn100: net(100, typedRate),
};

process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def test_withholding_tax_matches_display_and_calculation():
    result = _run()
    assert result["defaultRate"] == 19
    assert result["min"] == 0
    assert result["max"] == 50

    assert result["normalize"]["missing"] == 19
    assert result["normalize"]["junk"] == 19
    assert result["normalize"]["zero"] == 0
    assert result["normalize"]["spain"] == 19
    assert result["normalize"]["fraction"] == 19
    assert result["normalize"]["negative"] == 0
    assert result["normalize"]["cap"] == 50
    assert result["normalize"]["over"] == 50
    assert result["normalize"]["wayOver"] == 50

    # No saved rate uses the 19% default and writes that same number.
    assert result["fresh"] == {"rate": 19, "saved": "19"}
    assert result["kept"] == {"rate": 19, "saved": "19"}

    # A stored 60 is migrated to the 50 cap. Net dividends use 50, not 60.
    assert result["legacy"]["rate"] == 50
    assert result["legacy"]["saved"] == "50"
    assert result["legacy"]["netOn100"] == 50

    # Typing 60 stores 50, and the field is rewritten to that same 50.
    assert result["typed"]["rate"] == 50
    assert result["typed"]["saved"] == "50"
    assert result["typed"]["shown"] == "50"
    assert result["typed"]["netOn100"] == 50


if __name__ == "__main__":
    test_withholding_tax_matches_display_and_calculation()
    print("All withholding tax tests passed.")
