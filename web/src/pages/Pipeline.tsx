import dagre from '@dagrejs/dagre'
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getPipeline,
  rerun,
  type PipelineGraph,
  type PipelineNode,
  type Severity,
} from '../api/client'
import { Button, Card, Drawer, ErrorNote, Loading, PageTitle, SeverityChip } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useRunEvents, type RunEvent } from '../hooks/useRunEvents'

const NODE_WIDTH = 200
const NODE_HEIGHT = 86

const STATUS_STYLE: Record<string, string> = {
  ok: 'border-ok/50 bg-ok-soft',
  degraded: 'border-sev-warning/60 bg-sev-warning-soft',
  failed: 'border-sev-blocker/60 bg-sev-blocker-soft',
  running: 'border-ink/40 bg-surface animate-pulse',
  idle: 'border-line bg-surface',
}

type StepData = {
  node: PipelineNode
  live?: RunEvent
  onOpen: () => void
}

function StepCard({ data }: NodeProps) {
  const { node, live, onOpen } = data as unknown as StepData
  const status = (live?.status as string) ?? node.stats?.status ?? (live ? 'running' : 'idle')
  const rowsOut = (live?.rows_out as number) ?? node.stats?.rows_out
  const rowsIn = (live?.rows_in as number) ?? node.stats?.rows_in
  const quarantined = (live?.quarantined as number) ?? node.stats?.quarantined ?? 0
  const flags = (live?.flags as Record<string, number>) ?? node.stats?.flags ?? {}

  return (
    <button
      onClick={onOpen}
      style={{ width: NODE_WIDTH }}
      className={`rounded-lg border px-3 py-2 text-left shadow-sm transition hover:shadow ${
        STATUS_STYLE[status] ?? STATUS_STYLE.idle
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-ink-soft" />
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-semibold">{node.label}</span>
        <span className="text-[10px] uppercase tracking-wide text-ink-soft">{node.type}</span>
      </div>
      <div className="mt-1 text-[11px] tabular-nums text-ink-soft">
        {rowsIn !== undefined || rowsOut !== undefined ? (
          <>
            {rowsIn ?? 0} in · {rowsOut ?? 0} out
            {quarantined ? ` · ${quarantined} held` : ''}
          </>
        ) : (
          'not run'
        )}
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {(['BLOCKER', 'CRITICAL', 'WARNING', 'INFO'] as Severity[]).map((severity) =>
          flags[severity] ? (
            <SeverityChip key={severity} severity={severity} count={flags[severity]} />
          ) : null,
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-ink-soft" />
    </button>
  )
}

const nodeTypes = { step: StepCard }

function layout(graph: PipelineGraph, live: Map<string, RunEvent>, open: (id: string) => void) {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 70 })
  for (const node of graph.nodes) g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  for (const edge of graph.edges) g.setEdge(edge.source, edge.target)
  dagre.layout(g)

  const nodes: Node[] = graph.nodes.map((node) => {
    const position = g.node(node.id)
    return {
      id: node.id,
      type: 'step',
      position: { x: position.x - NODE_WIDTH / 2, y: position.y - NODE_HEIGHT / 2 },
      data: { node, live: live.get(node.id), onOpen: () => open(node.id) } as unknown as Record<
        string,
        unknown
      >,
    }
  })

  const edges: Edge[] = graph.edges.map((edge, index) => {
    const event = live.get(edge.source)
    const rows = (event?.rows_out as number) ?? edge.rows
    const active = Boolean(event) && !live.get(edge.target)
    return {
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      label: rows !== undefined && rows !== null ? String(rows) : edge.port,
      animated: active,
      style: { stroke: active ? '#111' : '#bbb' },
      labelStyle: { fontSize: 10, fill: '#666' },
    }
  })
  return { nodes, edges }
}

export default function Pipeline() {
  const [params, setParams] = useSearchParams()
  const runId = params.get('run') ?? 'latest'
  const [replaying, setReplaying] = useState(false)
  const graph = useApi(() => getPipeline(runId === 'latest' ? undefined : runId), [runId])
  const { byNode, done, events } = useRunEvents(runId, replaying)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    if (done) graph.reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done])

  const flow = useMemo(
    () => (graph.data ? layout(graph.data, byNode, setSelected) : { nodes: [], edges: [] }),
    [graph.data, byNode],
  )

  const node = graph.data?.nodes.find((item) => item.id === selected)

  return (
    <div className="flex h-full flex-col">
      <PageTitle
        title="Pipeline"
        subtitle={
          graph.data
            ? `${graph.data.pack} · ${graph.data.nodes.length} steps · run ${graph.data.run_id ?? '—'}`
            : 'The graph is a view of the pack configuration, not where the logic lives.'
        }
      />
      <div className="mb-3 flex items-center gap-2">
        <Button
          onClick={() => {
            setReplaying(false)
            setTimeout(() => setReplaying(true), 10)
          }}
        >
          Replay last run
        </Button>
        <Button
          onClick={async () => {
            const result = await rerun(runId)
            setParams({ run: result.run_id })
            setReplaying(false)
          }}
        >
          Re-run with current decisions
        </Button>
        <span className="ml-auto text-[11px] text-ink-soft">
          {events.length} events{done ? ' · finished' : events.length ? ' · streaming' : ''}
        </span>
      </div>

      {graph.error ? <ErrorNote error={graph.error} /> : null}
      {graph.loading && !graph.data ? <Loading what="Loading the graph" /> : null}

      <div className="min-h-[480px] flex-1 rounded-lg border border-line bg-surface">
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} size={1} color="#e6e6e6" />
          <MiniMap pannable zoomable className="!bg-surface-sunk" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      <Drawer open={Boolean(node)} onClose={() => setSelected(null)} title={node?.label ?? ''}>
        {node && (
          <div className="space-y-4 text-[13px]">
            <p className="text-ink-soft">{node.description}</p>
            <Card title="Ports">
              <div className="space-y-1 text-[12px]">
                <div>
                  <span className="text-ink-soft">Consumes: </span>
                  {node.consumes.join(', ') || '—'}
                </div>
                <div>
                  <span className="text-ink-soft">Produces: </span>
                  {node.produces.join(', ') || '—'}
                </div>
              </div>
            </Card>
            <Card title="Last run">
              {node.stats && Object.keys(node.stats).length ? (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
                  <dt className="text-ink-soft">Status</dt>
                  <dd>{node.stats.status}</dd>
                  <dt className="text-ink-soft">Rows in</dt>
                  <dd className="tabular-nums">{node.stats.rows_in}</dd>
                  <dt className="text-ink-soft">Rows out</dt>
                  <dd className="tabular-nums">{node.stats.rows_out}</dd>
                  <dt className="text-ink-soft">Quarantined</dt>
                  <dd className="tabular-nums">{node.stats.quarantined}</dd>
                  <dt className="text-ink-soft">Took</dt>
                  <dd className="tabular-nums">{node.stats.duration_ms} ms</dd>
                </dl>
              ) : (
                <p className="text-ink-soft">This step has not run yet.</p>
              )}
              {node.stats?.error && <ErrorNote error={node.stats.error} />}
            </Card>
            <a
              className="inline-block text-[12px] underline underline-offset-2"
              href={`/flags?node=${node.id}`}
            >
              See this step's findings
            </a>
          </div>
        )}
      </Drawer>
    </div>
  )
}
