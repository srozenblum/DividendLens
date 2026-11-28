"""Recommendation scoring, including the AXA / AT&T cases.

Run: python tests/test_scoring.py

The same table is scored by score_metrics in main.py and by static/scoring.js.
A mismatch fails the run.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main

ROOT = Path(__file__).resolve().parents[1]
SCORE_KEYS = (
    "perScore",
    "yieldScore",
    "debtScore",
    "bookScore",
    "payoutScore",
    "overallRecommendation",
    "sustainabilityWarning",
    "sectorProfile",
)

# Full metrics so "unavailable" does not hide the per/yield decision.
_AXA = {
    "sector": "Financial Services",
    "industry": "Insurance - Diversified",
    "per": 12.4,
    "dividendYield": 5.06,
    "debtToEbitda": 2.1,
    "priceToBook": 2.08,
    "payoutRatio": 62.5,
}
_T = {
    "sector": "Communication Services",
    "industry": "Telecom Services",
    "per": 12.4,
    "dividendYield": 4.78,
    "debtToEbitda": 3.93,
    "priceToBook": 1.47,
    "payoutRatio": 59.36,
}


def _case(name, expected, **overrides):
    base = dict(_AXA)
    base.update(overrides)
    base.setdefault("minYield", 4)
    base.setdefault("maxPer", 15)
    return {"name": name, "input": base, "expected": expected}


CASES = [
    _case("AXA-like defaults are strong buy", {
        "sectorProfile": "default",
        "perScore": "buy",
        "yieldScore": "buy",
        "debtScore": "safe",
        "bookScore": "expensive",
        "payoutScore": "high",
        "overallRecommendation": "strong_buy",
    }),
    _case("AXA-like yield above a 5% minimum stays strong buy", {
        "overallRecommendation": "strong_buy",
        "perScore": "buy",
        "yieldScore": "buy",
    }, minYield=5),
    _case("AXA-like yield below a 5.5% minimum is buy", {
        "overallRecommendation": "buy",
        "perScore": "buy",
        "yieldScore": "neutral",
    }, minYield=5.5),
    _case("AXA-like P/E above a 12x cap is buy", {
        "overallRecommendation": "buy",
        "perScore": "neutral",
        "yieldScore": "buy",
    }, maxPer=12),
    _case("AXA-like both sliders miss is neutral", {
        "overallRecommendation": "neutral",
        "perScore": "neutral",
        "yieldScore": "neutral",
    }, minYield=6, maxPer=12),
    _case("yield exactly at the minimum is a buy", {
        "overallRecommendation": "strong_buy",
        "perScore": "buy",
        "yieldScore": "buy",
    }, dividendYield=4.0, minYield=4),
    _case("yield just below the displayed minimum is not a buy", {
        "overallRecommendation": "buy",
        "perScore": "buy",
        "yieldScore": "neutral",
    }, dividendYield=3.994, minYield=4),
    _case("yield that displays as the minimum is a buy", {
        "overallRecommendation": "strong_buy",
        "perScore": "buy",
        "yieldScore": "buy",
    }, dividendYield=3.9999, minYield=4),
    _case("yield exactly at a 5% minimum is a buy", {
        "overallRecommendation": "strong_buy",
        "perScore": "buy",
        "yieldScore": "buy",
    }, dividendYield=5, minYield=5),
    _case("P/E exactly at the maximum is a buy", {
        "overallRecommendation": "strong_buy",
        "perScore": "buy",
        "yieldScore": "buy",
    }, per=15, maxPer=15),
    _case("P/E just above the displayed maximum is not a buy", {
        "overallRecommendation": "buy",
        "perScore": "neutral",
        "yieldScore": "buy",
    }, per=15.06, maxPer=15),
    _case("P/E that displays as the maximum is a buy", {
        "overallRecommendation": "strong_buy",
        "perScore": "buy",
        "yieldScore": "buy",
    }, per=15.04, maxPer=15),
    _case("P/E just under 15 that displays as 15.0 is a buy", {
        "overallRecommendation": "strong_buy",
        "perScore": "buy",
        "yieldScore": "buy",
    }, per=14.96, maxPer=15),
    _case("P/E exactly at a 12x cap is a buy", {
        "overallRecommendation": "strong_buy",
        "perScore": "buy",
        "yieldScore": "buy",
    }, per=12, maxPer=12),
    _case("cheap stock with a low yield is still buy", {
        "overallRecommendation": "buy",
        "perScore": "buy",
        "yieldScore": "low",
    }, dividendYield=1.5),
    _case("expensive P/E overrides a high yield", {
        "overallRecommendation": "avoid_overvalued",
        "perScore": "expensive",
        "yieldScore": "buy",
    }, per=25),
    _case("no dividend is avoid", {
        "overallRecommendation": "avoid_no_dividends",
        "yieldScore": "none",
    }, dividendYield=None),
    _case("too many missing inputs is insufficient data", {
        "overallRecommendation": "insufficient_data",
        "perScore": "unavailable",
        "yieldScore": "buy",
        "debtScore": "unavailable",
        "bookScore": "unavailable",
        "payoutScore": "unavailable",
    }, per=None, debtToEbitda=None, priceToBook=None, payoutRatio=None),
    _case("two missing inputs still score", {
        "overallRecommendation": "strong_buy",
        "debtScore": "unavailable",
        "bookScore": "unavailable",
    }, debtToEbitda=None, priceToBook=None),
    {
        "name": "AT&T-like defaults are strong buy",
        "input": {**_T, "minYield": 4, "maxPer": 15},
        "expected": {
            "sectorProfile": "default",
            "perScore": "buy",
            "yieldScore": "buy",
            "debtScore": "moderate",
            "bookScore": "fair",
            "payoutScore": "healthy",
            "overallRecommendation": "strong_buy",
        },
    },
    {
        "name": "AT&T-like yield misses a 5% minimum",
        "input": {**_T, "minYield": 5, "maxPer": 15},
        "expected": {
            "overallRecommendation": "buy",
            "perScore": "buy",
            "yieldScore": "neutral",
        },
    },
    {
        "name": "AT&T-like both sliders miss is neutral",
        "input": {**_T, "minYield": 5, "maxPer": 12},
        "expected": {
            "overallRecommendation": "neutral",
            "perScore": "neutral",
            "yieldScore": "neutral",
        },
    },
    _case("bank P/E uses its own thresholds and ignores the slider", {
        "sectorProfile": "bank",
        "perScore": "buy",
        "yieldScore": "neutral",
        "overallRecommendation": "buy",
    }, sector="Financial Services", industry="Banks - Regional", per=9, dividendYield=3, maxPer=8),
    _case("bank P/E of 12 is neutral", {
        "sectorProfile": "bank",
        "perScore": "neutral",
        "overallRecommendation": "buy",
    }, sector="Financial Services", industry="Banks - Diversified", per=12, dividendYield=5),
    _case("bank P/E of 16 is expensive", {
        "sectorProfile": "bank",
        "perScore": "expensive",
        "overallRecommendation": "avoid_overvalued",
    }, sector="Financial Services", industry="Banks - Regional", per=16, dividendYield=5),
    _case("tech P/E ignores a tight max P/E slider", {
        "sectorProfile": "tech",
        "perScore": "buy",
        "overallRecommendation": "strong_buy",
    }, sector="Technology", industry="Software - Infrastructure", per=18, maxPer=10),
    _case("tech P/E of 25 is neutral", {
        "sectorProfile": "tech",
        "perScore": "neutral",
        "overallRecommendation": "buy",
    }, sector="Technology", industry="Semiconductors", per=25),
    _case("tech P/E of 31 is expensive", {
        "sectorProfile": "tech",
        "perScore": "expensive",
        "overallRecommendation": "avoid_overvalued",
    }, sector="Technology", industry="Software - Application", per=31),
    _case("utility P/E of 17 is buy", {
        "sectorProfile": "utility",
        "perScore": "buy",
        "debtScore": "safe",
        "overallRecommendation": "strong_buy",
    }, sector="Utilities", industry="Utilities - Regulated Electric", per=17, debtToEbitda=3.5),
    _case("utility debt of 4.5 is moderate", {
        "sectorProfile": "utility",
        "perScore": "neutral",
        "debtScore": "moderate",
        "overallRecommendation": "buy",
    }, sector="Utilities", industry="Utilities - Diversified", per=20, debtToEbitda=4.5),
    _case("utility debt of 6 is high", {
        "sectorProfile": "utility",
        "debtScore": "high",
    }, sector="Utilities", industry="Utilities - Regulated Gas", debtToEbitda=6),
    _case("default debt of 3.5 is moderate", {
        "debtScore": "moderate",
    }, debtToEbitda=3.5),
    _case("REIT ignores P/E and the yield slider", {
        "sectorProfile": "reit",
        "perScore": "not_applicable",
        "yieldScore": "neutral",
        "bookScore": "fair",
        "overallRecommendation": "neutral",
    }, sector="Real Estate", industry="REIT - Retail", per=40, dividendYield=4, minYield=2, priceToBook=1.5),
    _case("REIT yield above 5 is buy and can be strong only if P/E were buy", {
        "sectorProfile": "reit",
        "perScore": "not_applicable",
        "yieldScore": "buy",
        "overallRecommendation": "buy",
    }, sector="Real Estate", industry="REIT - Diversified", dividendYield=6, minYield=8),
    _case("REIT yield under 3 is avoid", {
        "sectorProfile": "reit",
        "yieldScore": "low",
        "overallRecommendation": "avoid_overvalued",
    }, sector="Real Estate", industry="REIT - Office", dividendYield=2.5),
    _case("holding company does not become strong buy on yield alone", {
        "sectorProfile": "holding",
        "perScore": "not_applicable",
        "bookScore": "not_applicable",
        "payoutScore": "not_applicable",
        "yieldScore": "buy",
        "overallRecommendation": "buy",
    }, sector="Financial Services", industry="Conglomerates"),
    _case("bare Diversified industry is a holding", {
        "sectorProfile": "holding",
    }, sector="Financial Services", industry="Diversified"),
    _case("oil uses the P/E slider", {
        "sectorProfile": "oil",
        "perScore": "neutral",
        "overallRecommendation": "buy",
    }, sector="Energy", industry="Oil & Gas Integrated", per=16, maxPer=15),
    _case("oil under a looser P/E cap is strong buy", {
        "sectorProfile": "oil",
        "perScore": "buy",
        "overallRecommendation": "strong_buy",
    }, sector="Energy", industry="Oil & Gas Integrated", per=16, maxPer=18),
    _case("insurance life is the default profile", {
        "sectorProfile": "default",
        "overallRecommendation": "strong_buy",
    }, industry="Insurance - Life"),
    _case("payout boundaries", {
        "payoutScore": "low",
    }, payoutRatio=39.9),
    _case("payout at 40 is healthy", {"payoutScore": "healthy"}, payoutRatio=40),
    _case("payout at 60 is healthy", {"payoutScore": "healthy"}, payoutRatio=60),
    _case("payout at 80 is high", {"payoutScore": "high"}, payoutRatio=80),
    _case("payout above 80 is very high", {"payoutScore": "very_high"}, payoutRatio=80.1),
    _case("bank book under 1 is buy", {
        "sectorProfile": "bank",
        "bookScore": "buy",
    }, industry="Banks - Regional", priceToBook=0.9),
    _case("bank book at 1.5 is fair", {
        "sectorProfile": "bank",
        "bookScore": "fair",
    }, industry="Banks - Regional", priceToBook=1.5),
    _case("REIT book under 1.2 is buy", {
        "sectorProfile": "reit",
        "bookScore": "buy",
    }, sector="Real Estate", industry="REIT - Residential", priceToBook=1.1),
    _case("missing sustainability data does not warn", {
        "overallRecommendation": "strong_buy",
        "sustainabilityWarning": False,
    }, sector="Communication Services", industry="Telecom Services",
       fcfPayout=None, fcfDeficit=False, dividendCutRecent=False),
    _case("FCF payout above 100 downgrades strong buy", {
        "overallRecommendation": "buy",
        "perScore": "buy",
        "yieldScore": "buy",
        "sustainabilityWarning": True,
    }, sector="Communication Services", industry="Telecom Services", fcfPayout=100.01),
    _case("FCF payout of exactly 100 does not warn", {
        "overallRecommendation": "strong_buy",
        "sustainabilityWarning": False,
    }, sector="Communication Services", industry="Telecom Services", fcfPayout=100),
    _case("negative free cash flow downgrades strong buy", {
        "overallRecommendation": "buy",
        "sustainabilityWarning": True,
    }, sector="Communication Services", industry="Telecom Services", fcfPayout=None, fcfDeficit=True),
    _case("a recent dividend cut downgrades strong buy", {
        "overallRecommendation": "buy",
        "sustainabilityWarning": True,
    }, sector="Communication Services", industry="Telecom Services", dividendCutRecent=True),
    _case("a cut and an uncovered payout still only step down to buy", {
        "overallRecommendation": "buy",
        "sustainabilityWarning": True,
    }, sector="Communication Services", industry="Telecom Services", fcfPayout=140, dividendCutRecent=True),
    _case("warning does not push a buy any lower", {
        "overallRecommendation": "buy",
        "yieldScore": "neutral",
        "sustainabilityWarning": True,
    }, sector="Communication Services", industry="Telecom Services", dividendYield=3, fcfPayout=150),
    _case("warning does not change an overvalued label", {
        "overallRecommendation": "avoid_overvalued",
        "perScore": "expensive",
        "sustainabilityWarning": True,
    }, sector="Communication Services", industry="Telecom Services", per=25, fcfPayout=150),
    _case("insurer ignores an uncovered FCF payout", {
        "sectorProfile": "default",
        "overallRecommendation": "strong_buy",
        "sustainabilityWarning": False,
    }, fcfPayout=180, fcfDeficit=True),
    _case("insurance broker FCF payout above 100 downgrades strong buy", {
        "sectorProfile": "default",
        "overallRecommendation": "buy",
        "sustainabilityWarning": True,
    }, industry="Insurance Brokers", fcfPayout=140),
    _case("bank ignores an uncovered FCF payout", {
        "sectorProfile": "bank",
        "perScore": "buy",
        "yieldScore": "buy",
        "overallRecommendation": "strong_buy",
        "sustainabilityWarning": False,
    }, sector="Financial Services", industry="Banks - Regional", per=9, dividendYield=5,
       fcfPayout=250, fcfDeficit=True),
    _case("bank dividend cut still downgrades strong buy", {
        "sectorProfile": "bank",
        "overallRecommendation": "buy",
        "sustainabilityWarning": True,
    }, sector="Financial Services", industry="Banks - Regional", per=9, dividendYield=5,
       dividendCutRecent=True),
    _case("REIT FFO payout above 100 warns and stays buy", {
        "sectorProfile": "reit",
        "perScore": "not_applicable",
        "yieldScore": "buy",
        "overallRecommendation": "buy",
        "sustainabilityWarning": True,
    }, sector="Real Estate", industry="REIT - Retail", dividendYield=6, fcfPayout=130),
    _case("REIT covered FFO does not warn", {
        "sectorProfile": "reit",
        "overallRecommendation": "buy",
        "sustainabilityWarning": False,
    }, sector="Real Estate", industry="REIT - Residential", dividendYield=6, fcfPayout=70),
    _case("a non-boolean cut flag does not warn", {
        "overallRecommendation": "strong_buy",
        "sustainabilityWarning": False,
    }, sector="Communication Services", industry="Telecom Services", dividendCutRecent="yes"),
    _case("a numeric payout string still warns", {
        "overallRecommendation": "buy",
        "sustainabilityWarning": True,
    }, sector="Communication Services", industry="Telecom Services", fcfPayout="101"),
]


def _python_score(inp):
    scored = main.score_metrics(
        sector=inp.get("sector") or "",
        industry=inp.get("industry") or "",
        per=inp.get("per"),
        dividend_yield=inp.get("dividendYield"),
        debt_to_ebitda=inp.get("debtToEbitda"),
        price_to_book=inp.get("priceToBook"),
        payout_percent=inp.get("payoutRatio"),
        min_yield=inp.get("minYield", 4),
        max_per=inp.get("maxPer", 15),
        fcf_payout=inp.get("fcfPayout"),
        fcf_deficit=inp.get("fcfDeficit", False),
        dividend_cut=inp.get("dividendCutRecent", False),
    )
    return {key: scored[key] for key in SCORE_KEYS}


def _javascript_scores(cases):
    script = r"""
const fs = require("fs");
const { scoreMetrics, recommendationForItem } = require("./static/scoring.js");
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const scores = payload.cases.map((c) => scoreMetrics(c));
const fallbacks = payload.fallbacks.map((c) =>
  recommendationForItem(c.item, c.minYield, c.maxPer)
);
process.stdout.write(JSON.stringify({ scores, fallbacks }));
"""
    fallbacks = [
        {
            "item": {
                "symbol": "CS.PA",
                "recommendation": "buy",
                "sector": "Financial Services",
                "industry": "Insurance - Diversified",
                "per": 12.4,
                "divYield": 5.06,
                "notes": "keep me",
            },
            "minYield": 4,
            "maxPer": 15,
        },
        {
            "item": {
                "symbol": "CS.PA",
                "recommendation": "buy",
                "hasScoreInputs": True,
                "sector": "Financial Services",
                "industry": "Insurance - Diversified",
                "per": 12.4,
                "divYield": 5.06,
                "debtToEbitda": 2.1,
                "priceToBook": 2.08,
                "payoutRatio": 62.5,
                "notes": "keep me",
            },
            "minYield": 4,
            "maxPer": 15,
        },
        {
            "item": {
                "symbol": "T",
                "recommendation": "strong_buy",
                "hasScoreInputs": True,
                "sector": "Communication Services",
                "industry": "Telecom Services",
                "per": 12.4,
                "divYield": 4.78,
                "debtToEbitda": 3.93,
                "priceToBook": 1.47,
                "payoutRatio": 59.36,
            },
            "minYield": 5,
            "maxPer": 15,
        },
        {
            "item": {
                "symbol": "T",
                "recommendation": "strong_buy",
                "hasScoreInputs": True,
                "sector": "Communication Services",
                "industry": "Telecom Services",
                "per": 12.4,
                "divYield": 4.78,
                "debtToEbitda": 3.93,
                "priceToBook": 1.47,
                "payoutRatio": 59.36,
                "fcfPayout": 132,
                "fcfDeficit": False,
                "dividendCutRecent": False,
            },
            "minYield": 4,
            "maxPer": 15,
        },
        {
            "item": {
                "symbol": "CS.PA",
                "recommendation": "strong_buy",
                "hasScoreInputs": True,
                "sector": "Financial Services",
                "industry": "Insurance - Diversified",
                "per": 12.4,
                "divYield": 5.06,
                "debtToEbitda": 2.1,
                "priceToBook": 2.08,
                "payoutRatio": 62.5,
                "fcfPayout": 180,
                "fcfDeficit": True,
                "dividendCutRecent": False,
            },
            "minYield": 4,
            "maxPer": 15,
        },
    ]
    proc = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"cases": [c["input"] for c in cases], "fallbacks": fallbacks}),
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout), fallbacks


def test_python_and_javascript_agree():
    js_payload, fallbacks = _javascript_scores(CASES)
    js_scores = js_payload["scores"]
    assert len(js_scores) == len(CASES)
    for case, js in zip(CASES, js_scores):
        py = _python_score(case["input"])
        js_view = {key: js[key] for key in SCORE_KEYS}
        assert py == js_view, f"{case['name']}\n python={py}\n js={js_view}"
        for key, value in case["expected"].items():
            assert py[key] == value, f"{case['name']} {key}: {py[key]} != {value}"

    # A row saved before these fields existed keeps its snapshot label.
    assert js_payload["fallbacks"][0] == "buy"
    assert fallbacks[0]["item"]["notes"] == "keep me"
    assert "hasScoreInputs" not in fallbacks[0]["item"]
    # The same metrics, once stored, follow the current thresholds.
    assert js_payload["fallbacks"][1] == "strong_buy"
    assert js_payload["fallbacks"][2] == "buy"
    # Stored cash-payout and cut inputs move with the sliders, same as P/E.
    assert js_payload["fallbacks"][3] == "buy"
    # An insurer keeps Strong Buy: the stored FCF figure is not used.
    assert js_payload["fallbacks"][4] == "strong_buy"


def test_score_stock_includes_displayed_thresholds():
    """score_stock uses the same inclusive, display-precision comparison."""
    at_cap = {
        "sector": "Communication Services",
        "industry": "Telecom Services",
        "trailingPE": 15.04,
        "dividendRate": 4.0,
        "currentPrice": 100.0,
        "payoutRatio": 0.5,
        "priceToBook": 1.5,
    }
    scores = main.score_stock(at_cap, debt_to_ebitda=2.0, min_yield=4, max_per=15)
    assert main.dividend_yield_percent(at_cap) == 4.0
    assert scores["perScore"] == "buy"
    assert scores["yieldScore"] == "buy"
    assert scores["overallRecommendation"] == "strong_buy"

    just_over = dict(at_cap)
    just_over["trailingPE"] = 15.06
    just_over["dividendRate"] = 3.99
    over = main.score_stock(just_over, debt_to_ebitda=2.0, min_yield=4, max_per=15)
    assert over["perScore"] == "neutral"
    assert over["yieldScore"] == "neutral"
    assert over["overallRecommendation"] == "neutral"

    # Raw yield 3.9999 is stored as 4.00% before scoring, and that meets 4%.
    fuzzy = {
        "sector": "Communication Services",
        "industry": "Telecom Services",
        "trailingPE": 14.96,
        "dividendYield": 3.9999,
        "payoutRatio": 0.5,
        "priceToBook": 1.5,
    }
    fuzzy_scores = main.score_stock(fuzzy, debt_to_ebitda=2.0, min_yield=4, max_per=15)
    assert main.dividend_yield_percent(fuzzy) == 4.0
    assert fuzzy_scores["perScore"] == "buy"
    assert fuzzy_scores["yieldScore"] == "buy"


def test_axa_info_dict_is_not_a_holding():
    """CS.PA comes back from Yahoo as industry 'Insurance - Diversified'.

    Treating every 'diversified' industry as a holding made P/E not applicable,
    so Refresh stored BUY again and the label never moved.
    """
    info = {
        "sector": "Financial Services",
        "industry": "Insurance - Diversified",
        "trailingPE": 12.361186,
        "dividendRate": 2.32,
        "currentPrice": 45.85,
        "payoutRatio": 0.625,
        "priceToBook": 2.08,
    }
    scores = main.score_stock(info, debt_to_ebitda=2.1, min_yield=4, max_per=15)
    assert main.dividend_yield_percent(info) == 5.06
    assert scores["sectorProfile"] == "default"
    assert scores["perScore"] == "buy"
    assert scores["yieldScore"] == "buy"
    assert scores["overallRecommendation"] == "strong_buy"

    att = {
        "sector": "Communication Services",
        "industry": "Telecom Services",
        "trailingPE": 12.4,
        "dividendYield": 4.78,
        "payoutRatio": 0.5936,
        "priceToBook": 1.47,
    }
    att_scores = main.score_stock(att, debt_to_ebitda=3.93, min_yield=4, max_per=15)
    assert att_scores["sectorProfile"] == "default"
    assert att_scores["overallRecommendation"] == "strong_buy"
    # Same company stops being a strong buy when the yield floor moves past 4.78.
    raised = main.score_stock(att, debt_to_ebitda=3.93, min_yield=5, max_per=15)
    assert raised["overallRecommendation"] == "buy"


def test_threshold_query_names():
    assert main.resolve_score_thresholds(None, None, None, None) == (4.0, 15.0)
    assert main.resolve_score_thresholds(6, 12, 8, 10) == (6.0, 12.0)
    assert main.resolve_score_thresholds(None, None, 6, 10) == (6.0, 10.0)

    route = next(r for r in main.app.routes if getattr(r, "path", None) == "/api/analyze/{ticker}")
    names = {p.alias or p.name for p in route.dependant.query_params}
    # The page sends both spellings. FastAPI only binds declared names, and
    # the camelCase ones used to be dropped, so every score used 4% / 15x.
    assert {"min_yield", "max_per", "minYield", "maxPer"} <= names

    class FakeTicker:
        def __init__(self, symbol):
            self.info = {
                "quoteType": "EQUITY",
                "longName": "AXA SA",
                "currentPrice": 45.85,
                "currency": "EUR",
                "exchange": "PAR",
                "sector": "Financial Services",
                "industry": "Insurance - Diversified",
                "trailingPE": 12.361186,
                "dividendRate": 2.32,
                "payoutRatio": 0.625,
                "priceToBook": 2.08,
                "totalDebt": 100.0,
                "ebitda": 50.0,
            }
            self.balance_sheet = None
            self.financials = None
            self.calendar = None
            self.dividends = None

        def history(self, *args, **kwargs):
            return None

    import asyncio

    original = main.yf.Ticker
    main.yf.Ticker = FakeTicker
    try:
        plain = asyncio.run(main.analyze_ticker("CS.PA"))
        camel = asyncio.run(main.analyze_ticker("CS.PA", minYield=6, maxPer=15))
        snake = asyncio.run(main.analyze_ticker("CS.PA", min_yield=4, max_per=12))
    finally:
        main.yf.Ticker = original

    assert plain["scores"]["sectorProfile"] == "default"
    assert plain["scores"]["overallRecommendation"] == "strong_buy"
    assert plain["scoringInputs"]["industry"] == "Insurance - Diversified"
    assert plain["scoringInputs"]["dividendYield"] == 5.06
    assert camel["scores"]["overallRecommendation"] == "buy"
    assert camel["scores"]["yieldScore"] == "neutral"
    assert snake["scores"]["overallRecommendation"] == "buy"
    assert snake["scores"]["perScore"] == "neutral"


def _print_table():
    print("AXA-like (Insurance - Diversified, P/E 12.4, yield 5.06%) and")
    print("AT&T-like (Telecom Services, P/E 12.4, yield 4.78%)")
    print(f"{'min yield':>10} {'max P/E':>8} {'AXA':>18} {'AT&T':>18}")
    for min_yield, max_per in ((4, 15), (5, 15), (5.5, 15), (4, 12), (6, 12)):
        axa = _python_score({**_AXA, "minYield": min_yield, "maxPer": max_per})
        att = _python_score({**_T, "minYield": min_yield, "maxPer": max_per})
        print(f"{min_yield:10.1f} {max_per:8.0f} {axa['overallRecommendation']:>18} {att['overallRecommendation']:>18}")


if __name__ == "__main__":
    test_python_and_javascript_agree()
    test_score_stock_includes_displayed_thresholds()
    test_axa_info_dict_is_not_a_holding()
    test_threshold_query_names()
    _print_table()
    print(f"All scoring tests passed ({len(CASES)} cases, Python and JavaScript).")
