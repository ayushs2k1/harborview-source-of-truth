/** Honest stub for a screen that a later phase fills in. */
export default function Placeholder({ title, phase }: { title: string; phase: string }) {
  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      <p className="mt-1 text-sm text-ink-soft">Built in {phase}.</p>
    </div>
  )
}
