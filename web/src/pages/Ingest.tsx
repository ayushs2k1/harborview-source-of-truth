import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getHealth, listRuns, uploadFiles, type Health, type RunDetail } from '../api/client'
import { Button, Card, ErrorNote, PageTitle, SeverityChip } from '../components/ui'
import { useApi } from '../hooks/useApi'

const SOURCE_GUESS: [RegExp, string][] = [
  [/roster|hr|employee|staff/i, 'roster'],
  [/pay|payroll/i, 'payroll'],
  [/licen[cs]|credential|cert/i, 'credentials'],
  [/schedule|rota/i, 'schedule'],
  [/census/i, 'census'],
  [/vendor/i, 'vendor documents'],
]

function guess(name: string): string {
  if (name.toLowerCase().endsWith('.pdf')) return 'schedule (PDF)'
  for (const [pattern, label] of SOURCE_GUESS) if (pattern.test(name)) return label
  return 'detected from contents'
}

export default function Ingest() {
  const navigate = useNavigate()
  const [health, setHealth] = useState<Health | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [asOf, setAsOf] = useState('')
  const [pack, setPack] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [dragging, setDragging] = useState(false)
  const runs = useApi(() => listRuns(), [])

  useEffect(() => {
    getHealth()
      .then((value) => {
        setHealth(value)
        setAsOf((current) => current || value.today)
        setPack((current) => current || value.default_pack)
      })
      .catch(setError)
  }, [])

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      const { run_id } = await uploadFiles(files, { asOf, pack })
      navigate(`/pipeline?run=${run_id}`)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-4xl space-y-4">
      <PageTitle
        title="Ingest"
        subtitle="Drop the roster, payroll, credential and schedule files in. Types are detected from the contents, not the filenames."
      />

      {error ? <ErrorNote error={error} /> : null}

      <Card>
        <div
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            setFiles(Array.from(event.dataTransfer.files))
          }}
          className={`rounded-lg border-2 border-dashed px-6 py-10 text-center transition ${
            dragging ? 'border-ink bg-surface-sunk' : 'border-line'
          }`}
        >
          <p className="text-sm font-medium">Drop files here</p>
          <p className="mt-1 text-[12px] text-ink-soft">
            CSV, TSV, spreadsheets and PDFs. A file we cannot classify is flagged, never
            silently ignored.
          </p>
          <label className="mt-3 inline-block cursor-pointer rounded border border-line px-3 py-1.5 text-[13px] hover:bg-surface-sunk">
            Choose files
            <input
              type="file"
              multiple
              className="hidden"
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
          </label>
        </div>

        {files.length > 0 && (
          <ul className="mt-4 divide-y divide-line text-[13px]">
            {files.map((file) => (
              <li key={file.name} className="flex items-center justify-between py-1.5">
                <span className="font-medium">{file.name}</span>
                <span className="text-[11px] text-ink-soft">
                  {guess(file.name)} · {(file.size / 1024).toFixed(0)} KB
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <label className="text-[12px]">
            <div className="mb-1 text-ink-soft">As of</div>
            <input
              type="date"
              value={asOf}
              onChange={(event) => setAsOf(event.target.value)}
              className="rounded border border-line px-2 py-1 text-[13px]"
            />
          </label>
          <label className="text-[12px]">
            <div className="mb-1 text-ink-soft">Pack</div>
            <select
              value={pack}
              onChange={(event) => setPack(event.target.value)}
              className="rounded border border-line px-2 py-1 text-[13px]"
            >
              {(health?.packs ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="ml-auto">
            <Button tone="primary" onClick={start} disabled={busy || files.length === 0}>
              {busy ? 'Starting…' : `Ingest ${files.length || ''} file${files.length === 1 ? '' : 's'}`}
            </Button>
          </div>
        </div>
        <p className="mt-2 text-[11px] text-ink-soft">
          Compliance is judged as of the date of the work, not today, so the as-of date
          changes the answers.
        </p>
      </Card>

      <Card title="Recent runs">
        {runs.data?.runs?.length ? (
          <ul className="divide-y divide-line text-[13px]">
            {runs.data.runs.slice(0, 6).map((run: RunDetail) => (
              <li key={run.run_id} className="flex items-center gap-3 py-1.5">
                <button
                  className="font-mono text-[12px] underline-offset-2 hover:underline"
                  onClick={() => navigate(`/pipeline?run=${run.run_id}`)}
                >
                  {run.run_id}
                </button>
                <span className="text-[11px] text-ink-soft">
                  {run.pack} · as of {run.as_of}
                </span>
                <span className="ml-auto flex gap-1">
                  {(['BLOCKER', 'CRITICAL', 'WARNING', 'INFO'] as const).map((severity) =>
                    run.flags?.[severity] ? (
                      <SeverityChip key={severity} severity={severity} count={run.flags[severity]} />
                    ) : null,
                  )}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-ink-soft">No runs yet.</p>
        )}
      </Card>
    </div>
  )
}
