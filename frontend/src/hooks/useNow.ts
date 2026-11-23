/**
 * useNow — ticking wall clock for live readouts.
 *
 * The initial value is captured once (lazy useState initializer); after
 * mount only the interval updates it, so rendered output never calls
 * Date.now() directly (react-hooks/purity).
 */

import { useEffect, useState } from 'react';

export function useNow(intervalMs = 1_000): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return now;
}
