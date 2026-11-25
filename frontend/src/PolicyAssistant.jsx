import React, {useEffect, useRef, useState} from 'react';
import {Plus, Send, Sparkles} from 'lucide-react';
import './policy-assistant.css';
import PolicyEvaluation from './PolicyEvaluation.jsx';

const prompts = {
  receipt: 'What is my receipt threshold?',
  expense_summary: 'Summarize visible expenses',
  exceptions: 'Which expenses need attention?',
  policy_guidance: 'Explain my expense policy',
};
const money = new Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR', minimumFractionDigits: 0});

function supportedTask(question) {
  const text = question.toLowerCase().replace(/[?.!]+$/, '');
  if (/^(which expenses need attention|show (my )?(policy exceptions|flagged expenses))$/.test(text)) {
    return 'exceptions';
  }
  if (/^(summarize (my |visible )?expenses|(show )?(my )?expense summary|how much (did i spend|have i spent))$/.test(text)) {
    return 'expense_summary';
  }
  if (/^(what is (my |the )?receipt threshold|when (do i need|is) a receipt( required)?)$/.test(text)) {
    return 'receipt';
  }
  if (/^(what is (my |the )?expense limit|explain (my |the )?expense policy)$/.test(text)) {
    return 'policy_guidance';
  }
}

export default function PolicyAssistant({api, onNavigate}) {
  const [health, setHealth] = useState(null);
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const latest = useRef(null);
  const ready = health?.enabled && health?.configured;

  useEffect(() => {
    const request = new AbortController();
    api('/ai/health', {signal: request.signal})
      .then(setHealth)
      .catch(() => {
        if (!request.signal.aborted) setHealth({enabled: false});
      });
    return () => {
      request.abort();
      latest.current?.abort();
    };
  }, []);

  function reset() {
    latest.current?.abort();
    latest.current = null;
    setBusy(false);
    setQuery('');
    setMessages([]);
    setError('');
  }

  async function ask(value) {
    const question = value.trim();
    if (!question || !ready || latest.current) return;
    const request = new AbortController();
    latest.current = request;
    setBusy(true);
    setError('');
    try {
      let answer;
      const task = supportedTask(question);
      if (task === 'exceptions' || (task === 'expense_summary' && health.mode === 'mock')) {
        const personal = /\b(my|i)\b/i.test(question);
        const report = await api(personal ? '/ai/expense-report?scope=personal' : '/ai/expense-report',
          {signal: request.signal});
        answer = task === 'expense_summary' ? {
          metrics: report.metrics,
          personal,
          sources: report.sources,
          provider: 'deterministic',
        } : {
          answer: report.exceptions.length
            ? `${report.exceptions.length} of ${report.metrics.count} visible expenses have recorded policy flags.`
            : 'There are no recorded policy exceptions in your visible expenses.',
          sources: report.sources,
          expenses: report.exceptions,
          provider: 'deterministic',
        };
      } else if (health.mode === 'mock' && (task === 'receipt' || task === 'policy_guidance')) {
        const policies = await api('/ai/policy-summary', {signal: request.signal});
        answer = {policies, sources: policies.map(policy => policy.name), provider: 'deterministic'};
      } else if (task || health.mode !== 'mock') {
        answer = await api('/ai/execute', {
          method: 'POST',
          signal: request.signal,
          body: JSON.stringify({task: task === 'receipt' ? 'policy_guidance' : task || 'policy_guidance', query: question}),
        });
      } else {
        answer = {answer: 'Demo mode supports general expense policy, receipt thresholds, expense totals, and recorded exceptions. Choose a suggested question to get started.'};
      }
      if (request.signal.aborted) return;
      setMessages(previous => [...previous, {question, task, ...answer}]);
      setQuery('');
    } catch (failure) {
      if (!request.signal.aborted) setError(failure.message);
    } finally {
      if (latest.current === request) {
        latest.current = null;
        setBusy(false);
      }
    }
  }

  return <><PolicyEvaluation api={api}/><section className="air-panel policy-chat">
    <header className="air-row">
      <span>{health?.mode === 'mock' ? 'Demo mode · No live AI reasoning' : health?.mode || 'Policy guidance'}</span>
      <button className="outline" onClick={reset}><Plus size={16}/> New conversation</button>
    </header>
    {!messages.length && <div className="policy-chat-intro">
      <Sparkles size={24} aria-hidden="true"/>
      <h2>How can I help with your expenses?</h2>
      <div className="policy-prompts">
        {Object.values(prompts).map(prompt => <button className="outline" key={prompt} disabled={!ready || busy}
          onClick={() => ask(prompt)}>{prompt}</button>)}
      </div>
    </div>}
    <div className="policy-messages" aria-live="polite">
      {messages.map((message, index) => <div className="policy-turn" key={index}>
        <p className="policy-question">{message.question}</p>
        <article className="air-answer">
          {message.answer && <p>{message.answer}</p>}
          {message.metrics && <dl className="policy-metrics" aria-label={message.personal ? 'Personal expense summary' : 'Visible expense summary'}>
            <div><dt>Total spend</dt><dd>{money.format(message.metrics.total)}</dd></div>
            <div><dt>Expenses</dt><dd>{message.metrics.count}</dd></div>
            <div><dt>Policy exceptions</dt><dd>{message.metrics.exceptions}</dd></div>
          </dl>}
          {message.policies?.map(policy => <section key={policy.name}>
            <h3>{message.task === 'receipt' ? 'Receipt requirements' : policy.name}</h3>
            <p>A receipt is required for expenses above {money.format(policy.receipt_threshold)}.</p>
            {message.task !== 'receipt' && <p>Maximum expense amount {money.format(policy.max_expense)}.</p>}
          </section>)}
          {message.policies?.length === 0 && <p>No general expense policy applies to your profile.</p>}
          {message.expenses?.map(expense => <button className="air-text-button" key={expense.id}
            onClick={() => onNavigate(expense.id)}>{expense.merchant} · {expense.employee} · {expense.reason}</button>)}
          {!!message.sources?.length && <small>Sources: {message.sources.join(', ')}</small>}
          {message.provider && <small className="policy-provider">{message.provider === 'deterministic' || message.provider === 'mock'
            ? 'Calculated from TripLedger records' : `AI-generated · ${message.provider}`}</small>}
        </article>
      </div>)}
      {busy && <p role="status">Preparing a response…</p>}
    </div>
    {!!messages.length && <div className="policy-followups" aria-label="Suggested follow-ups">
      {(messages.at(-1).task === 'receipt' || messages.at(-1).task === 'expense_summary'
        ? ['exceptions', 'policy_guidance'] : ['receipt', 'expense_summary']).map(task =>
        <button className="outline" key={task} disabled={!ready || busy} onClick={() => ask(prompts[task])}>{prompts[task]}</button>)}
    </div>}
    {error && <p className="air-error" role="alert">{error}</p>}
    {!ready && <p role="status">{health ? 'Policy Assistant is unavailable.' : 'Checking assistant availability…'}</p>}
    <form className="policy-composer" onSubmit={event => {event.preventDefault(); ask(query);}}>
      <textarea aria-label="Ask about expenses or policy" placeholder="Ask about expenses or policy…"
        value={query} maxLength={2000} rows={2} disabled={!ready || busy}
        onChange={event => setQuery(event.target.value)}/>
      <button className="air-submit" aria-label="Send question" disabled={!ready || busy || !query.trim()}><Send size={18}/></button>
    </form>
  </section></>;
}
