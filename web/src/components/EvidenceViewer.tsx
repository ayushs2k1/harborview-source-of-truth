import { useState } from 'react'
import { api, type EvidenceItem } from '../api/client'
import { Chip, Loading } from './ui'

interface RowEvidence {
  file: string
  row_index: number
  status: string
  raw: Record<string, string>
  normalized: Record<string, string>
  context: { row_index: number; status: string; raw: Record<string, string> }[]
}

/**
 * The actual cell, or the actual rectangle on the page.
 *
 * A flag is only worth as much as the thing it points at, so the viewer shows the
 * source row with the column highlighted, or the rendered page with a box drawn on it.
 */
export default function EvidenceViewer({ evidence }: { evidence: EvidenceItem[] }) {
  const [index, setIndex] = useState(0)
  const item = evidence[index]
  if (!item) return null

  return (
    <div className="space-y-2">
      {evidence.length > 1 && (
        <div className="flex flex-wrap gap-1">
          {evidence.map((entry, position) => (
            <Chip
              key={position}
              tone={position === index ? 'ok' : 'neutral'}
              onClick={() => setIndex(position)}
            >
              {entry.page ? `page ${entry.page}` : `row ${entry.row}`}
            </Chip>
          ))}
        </div>
      )}
      {item.page && item.file_id ? (
        <PageEvidence item={item} />
      ) : item.row && item.file_id ? (
        <RowView fileId={item.file_id} row={item.row} column={item.column} />
      ) : (
        <p className="text-[12px] text-ink-soft">
          {item.source_type ? `From ${item.source_type}.` : 'No row-level evidence.'}
          {item.raw_value ? ` Value: ${item.raw_value}` : ''}
        </p>
      )}
    </div>
  )
}

function RowView({
  fileId,
  row,
  column,
}: {
  fileId: string
  row: number
  column: string | null
}) {
  const [data, setData] = useState<RowEvidence | null>(null)
  const [error, setError] = useState<string>('')

  if (!data && !error) {
    api<RowEvidence>(`/evidence/file/${fileId}/row/${row}`)
      .then(setData)
      .catch((reason: Error) => setError(reason.message))
    return <Loading what="Loading the row" />
  }
  if (error) return <p className="text-[12px] text-sev-critical">{error}</p>
  if (!data) return null

  return (
    <div className="space-y-1">
      <p className="text-[11px] text-ink-soft">
        {data.file} · row {data.row_index}
        {data.status !== 'ok' ? ` · ${data.status}` : ''}
      </p>
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full text-[12px]">
          <tbody>
            {Object.entries(data.raw).map(([key, value]) => {
              const highlighted = column && (key === column || key.toLowerCase() === column.toLowerCase())
              return (
                <tr key={key} className={highlighted ? 'bg-sev-warning-soft' : ''}>
                  <th className="w-40 border-b border-line/60 px-2 py-1 text-left font-medium text-ink-soft">
                    {key}
                  </th>
                  <td className="border-b border-line/60 px-2 py-1 font-mono">{value || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

//: Width the page image is displayed at. Boxes are stored in PDF points, so the
//: ratio to the page's own width is what converts them.
const DISPLAY_WIDTH = 760
const PAGE_WIDTH_POINTS = 792 // landscape letter, which is what a rota is printed on

function PageEvidence({ item }: { item: EvidenceItem }) {
  const box = item.bbox
  const ratio = DISPLAY_WIDTH / PAGE_WIDTH_POINTS
  const rect =
    box && box.length === 4
      ? {
          left: (box[0] ?? 0) * ratio,
          top: (box[1] ?? 0) * ratio,
          width: ((box[2] ?? 0) - (box[0] ?? 0)) * ratio,
          height: ((box[3] ?? 0) - (box[1] ?? 0)) * ratio,
        }
      : null
  return (
    <div>
      <p className="mb-1 text-[11px] text-ink-soft">
        {item.file} · page {item.page}
        {item.column ? ` · ${item.column}` : ''}
      </p>
      <div className="relative inline-block overflow-auto rounded border border-line">
        <img
          src={`/api/evidence/pdf/${item.file_id}/page/${item.page}.png`}
          alt={`Page ${item.page}`}
          className="block max-w-full"
          style={{ width: DISPLAY_WIDTH }}
        />
        {rect && (
          <span
            className="pointer-events-none absolute border-2 border-sev-critical"
            style={{
              left: `${rect.left}px`,
              top: `${rect.top}px`,
              width: `${rect.width}px`,
              height: `${rect.height}px`,
            }}
          />
        )}
      </div>
      {item.raw_value && (
        <p className="mt-1 text-[12px]">
          Cell read as <code className="rounded bg-surface-sunk px-1">{item.raw_value}</code>
        </p>
      )}
    </div>
  )
}
