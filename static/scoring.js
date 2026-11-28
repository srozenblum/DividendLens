// Recommendation scoring shared by the analysis card and the watchlist.
// Mirrors score_metrics / get_sector_profile in main.py. The Python tests
// load this file in Node and check the two sides agree.
//
// payoutRatio is a percent (62.5 means 62.5%), matching the API metric.
// dividendYield is a percent as well. minYield / maxPer are the settings
// sliders; profiles with their own thresholds ignore the slider that does
// not apply to them (see sectorProfile).
//
// A forward yield at or above the minimum is a buy, and a P/E at or below
// the maximum is a buy. Compare the figures the page prints: yield to 2
// decimals (4.00%) and P/E to 1 decimal (15.0x). 3.9999 is shown as 4.00%
// and meets a 4% minimum; 15.04 is shown as 15.0x and meets a 15x cap.

function sectorProfile(sector, industry) {
  const sec = String(sector || '').toLowerCase();
  const ind = String(industry || '').toLowerCase();
  if (sec.includes('real estate') || ind.includes('reit')) return 'reit';
  if (['bank', 'savings', 'mortgage', 'credit'].some(k => ind.includes(k))) return 'bank';
  if (sec.includes('utilities')) return 'utility';
  if (sec.includes('energy') || ['oil', 'gas', 'petroleum'].some(k => ind.includes(k))) return 'oil';
  if (sec.includes('technology')) return 'tech';
  if (isHoldingIndustry(ind)) return 'holding';
  return 'default';
}

// "Insurance - Diversified" is an operating insurer. Only an industry that
// is itself a conglomerate or holding company skips P/E and book value.
function isHoldingIndustry(ind) {
  if (ind.includes('conglomerate') || ind.includes('holding')) return true;
  return ['diversified', 'diversified financials', 'diversified financial services'].includes(ind.trim());
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

// Same rounding as the cards: yield toFixed(2), P/E toFixed(1).
function displayedNumber(value, digits) {
  const n = finiteNumber(value);
  if (n == null) return null;
  const parsed = Number(n.toFixed(digits));
  return Number.isFinite(parsed) ? parsed : null;
}

function scoreMetrics(input) {
  const src = input || {};
  const profile = sectorProfile(src.sector, src.industry);
  const minYield = finiteNumber(src.minYield);
  const maxPer = finiteNumber(src.maxPer);
  const minY = minYield == null ? 4 : minYield;
  const maxP = maxPer == null ? 15 : maxPer;

  let per = finiteNumber(src.per);
  if (per != null && per <= 0) per = null;
  const dividendYield = finiteNumber(src.dividendYield);
  const debtToEbitda = finiteNumber(src.debtToEbitda);
  const priceToBook = finiteNumber(src.priceToBook);
  const payoutRatio = finiteNumber(src.payoutRatio);

  let perScore;
  if (profile === 'reit' || profile === 'holding') perScore = 'not_applicable';
  else if (per == null) perScore = 'unavailable';
  else if (profile === 'bank') perScore = per < 10 ? 'buy' : (per <= 15 ? 'neutral' : 'expensive');
  else if (profile === 'tech') perScore = per < 20 ? 'buy' : (per <= 30 ? 'neutral' : 'expensive');
  else if (profile === 'utility') perScore = per < 18 ? 'buy' : (per <= 22 ? 'neutral' : 'expensive');
  else {
    const shownPer = displayedNumber(per, 1);
    const shownCap = displayedNumber(maxP, 1);
    perScore = shownPer <= shownCap ? 'buy' : (shownPer <= 20 ? 'neutral' : 'expensive');
  }

  let yieldScore;
  if (dividendYield == null) yieldScore = 'none';
  else if (profile === 'reit') yieldScore = dividendYield > 5 ? 'buy' : (dividendYield >= 3 ? 'neutral' : 'low');
  else {
    const shownYield = displayedNumber(dividendYield, 2);
    const shownMin = displayedNumber(minY, 2);
    yieldScore = shownYield >= shownMin ? 'buy' : (shownYield >= 2 ? 'neutral' : 'low');
  }

  let debtScore;
  if (debtToEbitda == null) debtScore = 'unavailable';
  else if (profile === 'utility') debtScore = debtToEbitda < 4 ? 'safe' : (debtToEbitda <= 5 ? 'moderate' : 'high');
  else debtScore = debtToEbitda < 3 ? 'safe' : (debtToEbitda <= 4 ? 'moderate' : 'high');

  let bookScore;
  if (profile === 'holding') bookScore = 'not_applicable';
  else if (priceToBook == null) bookScore = 'unavailable';
  else if (profile === 'bank') bookScore = priceToBook < 1 ? 'buy' : (priceToBook <= 1.5 ? 'fair' : 'expensive');
  else if (profile === 'reit') bookScore = priceToBook < 1.2 ? 'buy' : (priceToBook <= 2 ? 'fair' : 'expensive');
  else bookScore = priceToBook < 1 ? 'buy' : (priceToBook <= 2 ? 'fair' : 'expensive');

  let payoutScore;
  if (profile === 'holding') payoutScore = 'not_applicable';
  else if (payoutRatio == null) payoutScore = 'unavailable';
  else if (payoutRatio < 40) payoutScore = 'low';
  else if (payoutRatio <= 60) payoutScore = 'healthy';
  else if (payoutRatio <= 80) payoutScore = 'high';
  else payoutScore = 'very_high';

  const allScores = [perScore, yieldScore, debtScore, bookScore, payoutScore];
  const unavailableCount = allScores.filter(s => s === 'unavailable').length;

  let overallRecommendation;
  if (unavailableCount > 2) overallRecommendation = 'insufficient_data';
  else if (yieldScore === 'none') overallRecommendation = 'avoid_no_dividends';
  else if (perScore === 'buy' && yieldScore === 'buy') overallRecommendation = 'strong_buy';
  else if ((perScore === 'buy' || yieldScore === 'buy') && perScore !== 'expensive') overallRecommendation = 'buy';
  else if (perScore === 'expensive' || yieldScore === 'low') overallRecommendation = 'avoid_overvalued';
  else overallRecommendation = 'neutral';

  return {
    perScore,
    yieldScore,
    debtScore,
    bookScore,
    payoutScore,
    overallRecommendation,
    sectorProfile: profile,
  };
}

// Old watchlist rows stored only a snapshot label. Until a refresh writes
// the raw inputs, keep that label and leave the row untouched.
function recommendationForItem(item, minYield, maxPer) {
  if (!item || item.hasScoreInputs !== true) return (item && item.recommendation) || '';
  return scoreMetrics({
    sector: item.sector,
    industry: item.industry,
    per: item.per,
    dividendYield: item.divYield,
    debtToEbitda: item.debtToEbitda,
    priceToBook: item.priceToBook,
    payoutRatio: item.payoutRatio,
    minYield,
    maxPer,
  }).overallRecommendation;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { sectorProfile, scoreMetrics, recommendationForItem };
}
