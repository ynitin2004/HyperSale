import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Api, type EvalOutcome } from '../api/client'
import { navigate } from '../router'

// D37: blind labelling. The page never shows a model score; each rater sees only their own labels.
const OPTIONS: { value: EvalOutcome; label: string }[] = [
  { value: '1', label: '1 absent' }, { value: '2', label: '2 weak' }, { value: '3', label: '3 adequate' },
  { value: '4', label: '4 strong' }, { value: '5', label: '5 exemplary' },
  { value: 'insufficient_evidence', label: 'Not observable' },
]

export function RateListPage() {
  const items = useQuery({ queryKey: ['eval-items'], queryFn: Api.evalItems })
  if (items.isLoading) return <p className="muted">Loading the gold set…</p>
  if (items.error) return <p className="error">Could not load items: {String(items.error)}</p>
  const done = (items.data ?? []).filter((i) => i.labelled >= i.criteria).length
  return (
    <section>
      <h2>Label the gold set</h2>
      <p className="muted">
        Read each call and score only the rep, criterion by criterion. You will not see any model scores;
        your labels are independent of other raters'. {done} of {items.data?.length ?? 0} done.
      </p>
      {!items.data?.length && <p className="muted">No items in this workspace. Raters use their own Evals account.</p>}
      <table className="table" data-testid="eval-items">
        <thead><tr><th>Call</th><th>Scenario</th><th>Progress</th><th /></tr></thead>
        <tbody>
          {(items.data ?? []).map((i, n) => (
            <tr key={i.id}>
              <td>Call {n + 1}</td>
              <td>{i.scenario_slug}</td>
              <td><span className={`pill ${i.labelled >= i.criteria ? 'ready' : 'pending'}`}>{i.labelled}/{i.criteria}</span></td>
              <td><a href={`#/rate/${i.id}`}>{i.labelled ? 'Edit' : 'Label'} →</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export function RateItemPage({ itemId }: { itemId: string }) {
  const qc = useQueryClient()
  const item = useQuery({ queryKey: ['eval-item', itemId], queryFn: () => Api.evalItem(itemId) })
  const list = useQuery({ queryKey: ['eval-items'], queryFn: Api.evalItems })
  const [labels, setLabels] = useState<Record<string, EvalOutcome>>({})
  const [note, setNote] = useState('')
  useEffect(() => {
    if (item.data) { setLabels(item.data.my_labels); setNote(item.data.note ?? '') }
  }, [item.data])
  const save = useMutation({
    mutationFn: () => Api.saveLabels(itemId, { labels, note: note || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['eval-items'] })
      const ids = (list.data ?? []).map((i) => i.id)
      const next = ids[ids.indexOf(itemId) + 1]
      navigate(next ? `/rate/${next}` : '/rate')
    },
  })
  if (!item.data) return <p className="muted">Loading call…</p>
  const complete = item.data.criteria.every((c) => labels[c.id])
  return (
    <div className="split">
      <section>
        <p className="eyebrow"><a href="#/rate">← All calls</a></p>
        <h2>{item.data.scenario_title ?? item.data.scenario_slug}</h2>
        <ol className="transcript" data-testid="eval-transcript">
          {item.data.turns.map((t) => (
            <li key={t.idx} className={t.speaker}>
              <span className="who">[{t.idx}] {t.speaker === 'rep' ? 'Rep' : 'Buyer'}</span>
              <span>{t.text}</span>
            </li>
          ))}
        </ol>
      </section>
      <section>
        <h2>Your labels</h2>
        <form className="card" data-testid="label-form" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
          {item.data.criteria.map((c) => (
            <fieldset key={c.id} className="criterion">
              <legend><strong>{c.name}</strong></legend>
              <p className="muted small">{c.description}</p>
              <div className="choices">
                {OPTIONS.map((o) => (
                  <label key={o.value} className={labels[c.id] === o.value ? 'chosen' : ''}>
                    <input type="radio" name={c.id} value={o.value} checked={labels[c.id] === o.value}
                      onChange={() => setLabels({ ...labels, [c.id]: o.value })} />
                    {o.label}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <label className="small muted">Note (optional)
            <textarea maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
          </label>
          <button type="submit" disabled={!complete || save.isPending}>{save.isPending ? 'Saving…' : 'Save and next'}</button>
          {!complete && <p className="muted small">Label every criterion to save.</p>}
          {save.error && <p className="error">{String(save.error)}</p>}
        </form>
      </section>
    </div>
  )
}
