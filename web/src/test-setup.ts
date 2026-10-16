import '@testing-library/jest-dom/vitest'

// Existing translated-screen tests run in Hebrew; language.test covers the English default.
localStorage.setItem('iris-language', 'he')

// jsdom lacks these; Radix and the layout hooks use them.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub)
Element.prototype.scrollIntoView ??= () => {}
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.releasePointerCapture ??= () => {}

// Desktop by default in tests: min-width queries match, preference queries do not.
vi.stubGlobal(
  'matchMedia',
  vi.fn((query: string) => ({
    matches: query.includes('min-width'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  })),
)
