import { useEffect, useRef, useState } from 'react'

export interface RunEvent {
  seq: number
  ts: string
  type: string
  node_id?: string | null
  status?: string
  rows_in?: number
  rows_out?: number
  quarantined?: number
  duration_ms?: number
  flags?: Record<string, number>
  [key: string]: unknown
}

/**
 * Follow a run as it happens.
 *
 * A run still in flight streams live; a finished one replays from the stored log,
 * which is the demo-day fallback - the canvas lights up exactly as it did, with
 * nothing recomputed and nothing that can fail twice.
 */
export function useRunEvents(runId: string | null, replay = false) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [done, setDone] = useState(false)
  const source = useRef<EventSource | null>(null)

  useEffect(() => {
    setEvents([])
    setDone(false)
    if (!runId) return

    const stream = new EventSource(`/api/runs/${runId}/events${replay ? '?replay=true' : ''}`)
    source.current = stream

    const onMessage = (event: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(event.data) as RunEvent
        setEvents((current) => [...current, parsed])
        if (parsed.type === 'run_finished') {
          setDone(true)
          stream.close()
        }
      } catch {
        // A malformed frame is not worth taking the stream down for.
      }
    }

    for (const name of [
      'run_started',
      'node_started',
      'node_progress',
      'node_finished',
      'run_finished',
      'message',
    ]) {
      stream.addEventListener(name, onMessage as EventListener)
    }
    stream.onerror = () => {
      stream.close()
      setDone(true)
    }

    return () => {
      stream.close()
      source.current = null
    }
  }, [runId, replay])

  const byNode = new Map<string, RunEvent>()
  for (const event of events) {
    if (event.node_id) byNode.set(event.node_id, { ...byNode.get(event.node_id), ...event })
  }

  return { events, done, byNode }
}
