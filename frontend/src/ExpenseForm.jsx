import React, {useEffect, useRef, useState} from 'react';
import {Upload} from 'lucide-react';

const categories = ['Meals', 'Ground transport', 'Hotel', 'Airfare', 'Office supplies', 'Other'];

export default function ExpenseForm({projects, api, toast, submitDone}) {
  const [fields, setFields] = useState({
    project_code: projects[0]?.code || '',
    category: 'Meals',
    merchant: '',
    expense_date: '2026-11-21',
    amount: '',
    description: '',
  });
  const [receipt, setReceipt] = useState(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [savedExpense, setSavedExpense] = useState(null);
  const request = useRef(null);
  const editedDuringPreview = useRef(new Set());

  useEffect(() => () => request.current?.abort(), []);

  const field = name => ({
    value: fields[name],
    onChange: event => {
      editedDuringPreview.current.add(name);
      const value = event.target.value;
      setFields(previous => ({...previous, [name]: value}));
    },
  });

  async function selectReceipt(event) {
    request.current?.abort();
    const input = event.target;
    const file = input.files[0];
    setReceipt(file || null);
    setMessage('');
    if (!file || savedExpense !== null) return;

    const controller = new AbortController();
    request.current = controller;
    editedDuringPreview.current.clear();
    const body = new FormData();
    body.append('file', file);
    setMessage('Checking the receipt for demo suggestions…');
    try {
      const result = await api('/ai/receipt-preview', {method: 'POST', body, signal: controller.signal});
      if (controller.signal.aborted) return;
      if (result.fields) {
        const suggestions = Object.fromEntries(Object.entries(result.fields)
          .filter(([name]) => !editedDuringPreview.current.has(name)));
        setFields(previous => ({...previous, ...suggestions}));
        setMessage('Receipt details filled in. Edit them if needed.');
      } else {
        setMessage('Enter the receipt details manually.');
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error.status === 400) {
        input.value = '';
        setReceipt(null);
      }
      setMessage(error.status === 400 ? error.message : 'Receipt preview is unavailable. Enter expense details manually.');
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    request.current?.abort();
    setBusy(true);
    let expenseId = savedExpense;
    try {
      if (expenseId === null) {
        const expense = await api('/expenses', {
          method: 'POST',
          body: JSON.stringify({...fields, merchant: fields.merchant.trim(), amount: Number(fields.amount)}),
        });
        expenseId = expense.id;
        setSavedExpense(expenseId);
      }
      if (receipt) {
        const body = new FormData();
        body.append('file', receipt);
        await api(`/expenses/${expenseId}/receipt`, {method: 'POST', body});
      }
      toast('Expense submitted');
      submitDone();
    } catch (error) {
      toast(error.message);
    } finally {
      setBusy(false);
    }
  }

  return <form onSubmit={submit}>
    <div className="form-grid">
      <label className="field wide upload">
        <Upload/><span><b>Attach receipt</b><small>{receipt?.name || 'PDF, JPG or PNG · optional demo preview'}</small></span>
        <input type="file" accept=".pdf,.jpg,.jpeg,.png" disabled={busy} onChange={selectReceipt}/>
      </label>
      {message && <div className="field wide ai-note" role="status">{message}</div>}
    </div>
    <fieldset className="form-grid" disabled={busy || savedExpense !== null} style={{border: 0, padding: 0, margin: 0}}>
      <label className="field">Project<select required {...field('project_code')}>
        <option value="" disabled>Select a project</option>
        {projects.map(project => <option key={project.code} value={project.code}>{project.code} · {project.name}</option>)}
      </select></label>
      <label className="field">Category<select {...field('category')}>
        {categories.map(category => <option key={category}>{category}</option>)}
      </select></label>
      <label className="field wide">Merchant<input required pattern=".*\S.*" {...field('merchant')} /></label>
      <label className="field">Date<input type="date" required {...field('expense_date')}/></label>
      <label className="field">Amount (INR)<input type="number" min="0.01" step="0.01" required {...field('amount')}/></label>
      <label className="field wide">Description<input {...field('description')}/></label>
    </fieldset>
    {savedExpense !== null && <p role="status">Expense saved. Retry the receipt upload or close and attach it later.</p>}
    <div className="form-actions">
      <button className="primary" disabled={busy || (savedExpense !== null && !receipt)}>
        {busy ? 'Saving…' : savedExpense !== null ? 'Retry receipt upload' : 'Submit expense'}
      </button>
    </div>
  </form>;
}
