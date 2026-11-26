import React, {useEffect, useRef, useState} from 'react';

const fields = [
  ['travel_destination', 'Destination', 'text'],
  ['travel_dates.start_date', 'Check-in', 'date'],
  ['travel_dates.end_date', 'Check-out', 'date'],
  ['expense_amount', 'Claimed amount (INR)', 'number'],
];
const titles = {
  WITHIN_LIMIT: 'Within the sample limit',
  SOFT_FLAG: 'Manager review required',
  NEEDS_INFORMATION: 'More information needed',
  HUMAN_REVIEW: 'Policy reviewer needed',
};
const demoQuestion = 'Can I claim ₹18,400 for two hotel nights in Bengaluru?';

function hasInvalidStay(values) {
  const checkIn = values['travel_dates.start_date'];
  const checkOut = values['travel_dates.end_date'];
  return Boolean(checkIn && checkOut && checkOut <= checkIn);
}

export default function PolicyEvaluation({api}) {
  const [query, setQuery] = useState('');
  const [inputs, setInputs] = useState({});
  const [decision, setDecision] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(null);

  useEffect(() => () => pending.current?.abort(), []);

  async function evaluate(question, values, sessionId) {
    if (pending.current) return;
    const request = new AbortController();
    pending.current = request;
    setBusy(true);
    setError('');
    try {
      const result = await api('/ai/policy-evaluations', {
        method: 'POST',
        signal: request.signal,
        body: JSON.stringify({
          session_id: sessionId,
          user_query: question.trim(),
          structured_inputs: {
            travel_destination: values.travel_destination?.trim() || null,
            travel_dates: {
              start_date: values['travel_dates.start_date'] || null,
              end_date: values['travel_dates.end_date'] || null,
            },
            expense_amount: values.expense_amount ? {value: values.expense_amount, currency: 'INR'} : null,
          },
        }),
      });
      if (!request.signal.aborted) setDecision(result);
    } catch (failure) {
      if (!request.signal.aborted) setError(failure.message);
    } finally {
      if (pending.current === request) {
        pending.current = null;
        setBusy(false);
      }
    }
  }

  function tryExample() {
    const example = {travel_destination: 'Bengaluru', expense_amount: '18400'};
    setQuery(demoQuestion);
    setInputs(example);
    setDecision(null);
    evaluate(demoQuestion, example, null);
  }

  const allowance = decision?.allowed_expense_amount;
  const needsInformation = decision?.decision_category === 'NEEDS_INFORMATION';
  const invalidStay = hasInvalidStay(inputs);

  return <section className="air-panel policy-evaluation">
    <div className="air-row">
      <h2>Check a hotel expense</h2>
      <button className="outline" type="button" onClick={tryExample} disabled={busy}>Try hotel example</button>
    </div>
    <p>Demo policy check. Enter the stay details to see the sample decision.</p>
    <form onSubmit={event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.currentTarget));
      setInputs(values);
      if (hasInvalidStay(values)) {
        setError('');
        return;
      }
      evaluate(query, values, decision?.session_id || null);
    }}>
      <label className="field">Question
        <textarea maxLength={2000} rows={2} value={query} disabled={busy}
          onChange={event => setQuery(event.target.value)} placeholder="Can I claim this hotel expense?"/>
      </label>
      <div className="form-grid">
        {fields.map(([key, label, type]) => <label className="field" key={key}>{label}
          <input name={key} type={type} value={inputs[key] || ''} disabled={busy}
            aria-invalid={(key === 'travel_dates.end_date' && invalidStay)
              || (needsInformation && decision.missing_required_fields.includes(key) && !inputs[key])}
            aria-describedby={key === 'travel_dates.end_date' && invalidStay ? 'policy-stay-date-error' : undefined}
            min={type === 'number' ? '0.01' : undefined} step={type === 'number' ? '0.01' : undefined}
            maxLength={type === 'text' ? 100 : undefined}
            onChange={event => {
              const value = event.target.value;
              setInputs(previous => ({...previous, [key]: value}));
            }}/>
        </label>)}
      </div>
      {invalidStay && <p className="air-error" id="policy-stay-date-error" role="alert">Check-out must be after check-in.</p>}
      <div className="form-actions">
        <button className="primary" disabled={busy}>{busy ? 'Checking…' : needsInformation ? 'Recheck expense' : 'Check policy'}</button>
      </div>
    </form>
    {error && <p className="air-error" role="alert">{error}</p>}
    {decision && !invalidStay && <article className="air-answer" aria-live="polite">
      <h3>{titles[decision.decision_category]}</h3>
      <p>{decision.violation_explanation}</p>
      {allowance && <p><strong>Sample limit</strong> {new Intl.NumberFormat('en-IN', {
        style: 'currency', currency: allowance.currency,
      }).format(Number(allowance.value))}</p>}
      {needsInformation && <ul>
        {fields.filter(([key]) => decision.missing_required_fields.includes(key))
          .map(([key, label]) => <li key={key}>{label}</li>)}
      </ul>}
      <p><strong>Next step</strong> {decision.recommended_action}</p>
      {!!decision.applicable_policy_references.length && <p>Sample policy references {decision.applicable_policy_references.join(' · ')}</p>}
      <p>{decision.advisory_notice}</p>
      <small>Request ID {decision.request_id}</small>
    </article>}
  </section>;
}
