import { bandFor, verdictFor, type Pair } from './bands'

// Same defaults and cases as tests/test_thresholds.py, so the two implementations cannot drift.
const T: Record<string, Pair> = {
  violence: { low: 0.2, high: 0.7 },
  'sexual/minors': { low: 0.05, high: 0.3 },
  'self-harm/intent': { low: 0.1, high: 0.4 },
  'harassment/threatening': { low: 0.15, high: 0.5 },
  sexual: { low: 0.15, high: 0.6 },
  'violence/graphic': { low: 0.15, high: 0.6 },
}

test.each([
  ['violence', 0.19999, 'safe'],
  ['violence', 0.2, 'inconclusive'],
  ['violence', 0.69999, 'inconclusive'],
  ['violence', 0.7, 'harmful'],
  ['sexual/minors', 0.049, 'safe'],
  ['sexual/minors', 0.05, 'inconclusive'],
  ['sexual/minors', 0.3, 'harmful'],
  ['self-harm/intent', 0.1, 'inconclusive'],
  ['self-harm/intent', 0.4, 'harmful'],
  ['harassment/threatening', 0.15, 'inconclusive'],
  ['harassment/threatening', 0.5, 'harmful'],
  ['sexual', 0.6, 'harmful'],
  ['violence/graphic', 0.14, 'safe'],
])('%s at %s is %s', (cat, score, band) => {
  expect(bandFor({ [cat]: score }, T).band).toBe(band)
})

test('any high wins and lists both hit sets', () => {
  const r = bandFor({ violence: 0.3, hate: 0.9 }, { ...T, hate: { low: 0.2, high: 0.7 } })
  expect(r.band).toBe('harmful')
  expect(r.high).toEqual(['hate'])
  expect(r.low.sort()).toEqual(['hate', 'violence'])
})

test('an unknown category uses the general pair', () => {
  expect(bandFor({ 'brand-new': 0.25 }, T).band).toBe('inconclusive')
  expect(bandFor({ 'brand-new': 0.05 }, T).band).toBe('safe')
})

test('verdict follows the pipeline', () => {
  expect(verdictFor('safe')).toBe('safe')
  expect(verdictFor('harmful', 'safe')).toBe('harmful')
  expect(verdictFor('inconclusive')).toBe('review')
  expect(verdictFor('inconclusive', 'inconclusive')).toBe('review')
  expect(verdictFor('inconclusive', 'harmful')).toBe('harmful')
  expect(verdictFor('inconclusive', 'safe')).toBe('safe')
})
