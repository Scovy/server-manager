/**
 * Vitest setup file — extends matchers with jest-dom assertions.
 *
 * This adds matchers like:
 * - toBeInTheDocument()
 * - toHaveTextContent()
 * - toBeVisible()
 * - toHaveAttribute()
 */
import '@testing-library/jest-dom';

global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
