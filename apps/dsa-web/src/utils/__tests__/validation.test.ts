import { describe, expect, it } from 'vitest';
import { isObviouslyInvalidStockQuery, looksLikeStockCode, validateStockCode } from '../validation';

describe('validateStockCode — Taiwan (TW) formats', () => {
  // Mirrors data_provider/tw_market.py _extract_tw_body contract.
  const validTwCases = [
    '2330.TW', // listed (TWSE) suffix
    '6488.TWO', // OTC (TPEX) suffix
    '00878.TW', // 5-digit ETF with suffix
    '00675L.TW', // leveraged ETF (trailing letter) with suffix
    'TW2330', // canonical prefix form
    'TW00878', // prefixed ETF
    '2330', // bare 4-digit (A-share=6, HK=5, no clash)
    '0050', // bare 4-digit ETF
  ];

  it.each(validTwCases)('accepts %s', (code) => {
    expect(validateStockCode(code).valid).toBe(true);
    expect(looksLikeStockCode(code)).toBe(true);
  });

  it('normalizes lowercase TW codes to upper case', () => {
    expect(validateStockCode('2330.tw').normalized).toBe('2330.TW');
    expect(validateStockCode('tw2330').valid).toBe(true);
  });

  it('does not pre-reject canonical TW codes as invalid free-text queries', () => {
    // Regression: previously 2330.TW / TW2330 were blocked by isObviouslyInvalidStockQuery
    expect(isObviouslyInvalidStockQuery('2330.TW')).toBe(false);
    expect(isObviouslyInvalidStockQuery('TW2330')).toBe(false);
  });

  it('rejects TW-shaped codes with an out-of-range body', () => {
    expect(validateStockCode('123.TW').valid).toBe(false); // body < 4 digits
    expect(validateStockCode('1234567.TW').valid).toBe(false); // body > 6 digits
    expect(validateStockCode('233').valid).toBe(false); // bare 3-digit
  });
});

describe('validateStockCode — existing markets unaffected', () => {
  it('still accepts A-share / HK / US codes', () => {
    expect(validateStockCode('600519').valid).toBe(true); // A-share 6-digit
    expect(validateStockCode('00700').valid).toBe(true); // HK 5-digit
    expect(validateStockCode('HK00700').valid).toBe(true);
    expect(validateStockCode('AAPL').valid).toBe(true);
  });

  it('keeps bare 5-digit as a (HK) code, not a TW code', () => {
    // 5-digit bare codes stay HK by convention; TW 5-digit needs TW prefix / .TW suffix.
    expect(looksLikeStockCode('23300')).toBe(true);
    expect(looksLikeStockCode('00675L')).toBe(false); // bare letter-suffixed needs TW marker
  });

  it('still rejects clearly invalid input', () => {
    expect(validateStockCode('').valid).toBe(false);
    expect(validateStockCode('2330.XYZ').valid).toBe(false);
  });
});
