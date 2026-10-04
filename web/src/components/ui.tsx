import type { ReactNode } from 'react'
import type { Severity } from '../api/client'

/** Severity colours are always paired with the word, never colour alone: a projector
 *  at the back of a room flattens amber into grey, and not everybody sees red. */
const SEVERITY_STYLE: Record<Severity, string> = {
  BLOCKER: 'bg-sev-blocker-soft text-sev-blocker border-sev-blocker/30',
  CRITICAL: 'bg-sev-critical-soft text-sev-critical border-sev-critical/30',
  WARNING: 'bg-sev-warning-soft text-sev-warning border-sev-warning/40',
  INFO: 'bg-sev-info-soft text-sev-info border-sev-info/30',
}

const SEVERITY_ICON: Record<Severity, string> = {
  BLOCKER: '■',
  CRITICAL: '▲',
  WARNING: '●',
  INFO: 'ⓘ',
}

export function SeverityChip({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium ${SEVERITY_STYLE[severity]}`}
    >
      <span aria-hidden>{SEVERITY_ICON[severity]}</span>
      {severity}
      {count !== undefined && <span className="tabular-nums opacity-70">{count}</span>}
    </span>
  )
}

export function Chip({
  children,
  tone = 'neutral',
  onClick,
  title,
}: {
  children: ReactNode
  tone?: 'neutral' | 'ok' | 'warn' | 'bad' | 'unknown'
  onClick?: () => void
  title?: string
}) {
  const tones = {
    neutral: 'bg-surface-sunk text-ink-soft border-line',
    ok: 'bg-ok-soft text-ok border-ok/30',
    warn: 'bg-sev-warning-soft text-sev-warning border-sev-warning/40',
    bad: 'bg-sev-critical-soft text-sev-critical border-sev-critical/30',
    unknown: 'bg-surface-sunk text-unknown border-line',
  }
  const Tag = onClick ? 'button' : 'span'
  return (
    <Tag
      onClick={onClick}
      title={title}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] ${tones[tone]} ${onClick ? 'hover:brightness-95' : ''}`}
    >
      {children}
    </Tag>
  )
}

/** Three-valued display. Unknown is never shown as a tick. */
export function TriChip({ value }: { value: string }) {
  if (value === 'PASS') return <Chip tone="ok">✓ pass</Chip>
  if (value === 'FAIL') return <Chip tone="bad">✕ fail</Chip>
  return <Chip tone="unknown">? unknown</Chip>
}

export function Card({
  title,
  children,
  actions,
  className = '',
}: {
  title?: ReactNode
  children: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
          <h2 className="text-[13px] font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function Kpi({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: ReactNode
  hint?: string
  tone?: 'neutral' | 'ok' | 'warn' | 'bad'
}) {
  const tones = {
    neutral: 'text-ink',
    ok: 'text-ok',
    warn: 'text-sev-warning',
    bad: 'text-sev-critical',
  }
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-ink-soft">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${tones[tone]}`}>{value}</div>
      {hint && <div className="text-[11px] text-ink-soft">{hint}</div>}
    </div>
  )
}

export function Table({
  head,
  children,
  empty,
}: {
  head: ReactNode[]
  children: ReactNode
  empty?: boolean
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-ink-soft">
            {head.map((cell, index) => (
              <th key={index} className="px-2 py-1.5 font-medium">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {empty ? (
            <tr>
              <td colSpan={head.length} className="px-2 py-6 text-center text-ink-soft">
                Nothing to show.
              </td>
            </tr>
          ) : (
            children
          )}
        </tbody>
      </table>
    </div>
  )
}

export function Row({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  return (
    <tr
      onClick={onClick}
      className={`border-b border-line/60 ${onClick ? 'cursor-pointer hover:bg-surface-sunk' : ''}`}
    >
      {children}
    </tr>
  )
}

export function Cell({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <td className={`px-2 py-1.5 align-top ${className}`}>{children}</td>
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  width = 'w-[520px]',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  width?: string
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        aria-label="Close"
        className="flex-1 bg-black/20"
        onClick={onClose}
      />
      <aside className={`${width} max-w-full overflow-y-auto border-l border-line bg-surface`}>
        <header className="sticky top-0 flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
          <h2 className="text-[13px] font-semibold">{title}</h2>
          <button
            onClick={onClose}
            className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-soft hover:bg-surface-sunk"
          >
            Close
          </button>
        </header>
        <div className="p-4">{children}</div>
      </aside>
    </div>
  )
}

export function Button({
  children,
  onClick,
  tone = 'default',
  disabled,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  tone?: 'default' | 'primary'
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  const tones = {
    default: 'border-line bg-surface hover:bg-surface-sunk',
    primary: 'border-ink bg-ink text-white hover:opacity-90',
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded border px-3 py-1.5 text-[13px] font-medium disabled:cursor-not-allowed disabled:opacity-50 ${tones[tone]}`}
    >
      {children}
    </button>
  )
}

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <p className="py-8 text-center text-sm text-ink-soft">{what}…</p>
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error)
  return (
    <p className="rounded border border-sev-critical/30 bg-sev-critical-soft px-3 py-2 text-sm text-sev-critical">
      {message}
    </p>
  )
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: ReactNode }) {
  return (
    <header className="mb-4">
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      {subtitle && <p className="mt-0.5 text-[13px] text-ink-soft">{subtitle}</p>}
    </header>
  )
}
