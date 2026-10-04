import { useCallback, useEffect, useState } from 'react'

/** Load something from the API, with the three states a screen actually has. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    load()
      .then((value) => {
        if (!cancelled) {
          setData(value)
          setError(null)
        }
      })
      .catch((reason: unknown) => !cancelled && setError(reason))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, error, loading, reload }
}
