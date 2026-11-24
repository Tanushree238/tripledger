import asyncio, os, unittest
from unittest.mock import patch
import httpx
from pathlib import Path
from test_release import app
from fastapi.testclient import TestClient
from app.ai.providers import HTTPProvider
from app.ai.contracts import AIRequest, Context

class AIFoundation(unittest.TestCase):
 def test_receipt_preview_is_read_only_and_matches_fixture_content(self):
  fixture = Path(__file__).resolve().parents[1] / 'app' / 'demo_receipts' / 'lemon-tree-demo.pdf'
  with TestClient(app) as client, patch.dict(os.environ, {'AI_MODE':'mock','AI_ENABLED':'true'}):
   headers = {'X-Demo-User':'aarav@northstar.demo'}
   before = client.get('/expenses', headers=headers).json()
   response = client.post('/ai/receipt-preview', headers=headers,
                          files={'file': ('renamed.pdf', fixture.read_bytes(), 'application/pdf')})
   self.assertEqual(response.status_code, 200, response.text)
   self.assertEqual(response.json(), {'provider':'mock', 'fields':{
       'merchant':'Lemon Tree', 'amount':12600, 'expense_date':'2026-11-16', 'category':'Hotel'}})
   response = client.post('/ai/receipt-preview', headers=headers,
                          files={'file': (fixture.name, b'%PDF-1.4\nunknown', 'application/pdf')})
   self.assertIsNone(response.json()['fields'])
   bad_file = {'file': ('invalid.pdf', b'invalid', 'application/pdf')}
   self.assertEqual(client.post('/ai/receipt-preview', headers=headers, files=bad_file).status_code, 400)
   self.assertEqual(client.post('/ai/receipt-preview', headers={'X-Demo-User':'unknown'},
                                files=bad_file).status_code, 401)
   with patch.dict(os.environ, {'AI_MODE':'rag'}):
    self.assertEqual(client.post('/ai/receipt-preview', headers=headers, files=bad_file).status_code, 503)
   self.assertEqual(client.get('/expenses', headers=headers).json(), before)

 def test_scopes_and_validation(self):
  with TestClient(app) as c, patch.dict(os.environ, {'AI_MODE':'mock','AI_ENABLED':'true'}):
   def run(name, task='expense_summary'):
    return c.post('/ai/execute', headers={'X-Demo-User':name+'@northstar.demo'}, json={'task':task})
   self.assertIn('Visible expenses: 2',run('aarav').json()['answer'])
   self.assertIn('Visible expenses: 4',run('devika').json()['answer'])
   self.assertIn('Visible expenses: 2',run('nisha').json()['answer'])
   self.assertIn('25,000',run('nisha','policy_guidance').json()['answer'])
   self.assertEqual(run('unknown').status_code,401)
   self.assertEqual(c.post('/ai/execute',json={'task':'delete_expenses'}).status_code,422)
   self.assertEqual(c.post('/ai/execute',json={'task':'expense_summary','role':'finance'}).status_code,422)
   with patch.dict(os.environ,{'AI_ENABLED':'false'}): self.assertEqual(run('aarav').status_code,503)
   with patch.dict(os.environ,{'AI_MODE':'rag','AI_SERVICE_URL':''}): self.assertEqual(run('aarav').status_code,503)
   self.assertEqual(c.get('/expenses').status_code,200)
   policy=c.get('/ai/policy-summary',headers={'X-Demo-User':'aarav@northstar.demo'}).json()
   self.assertEqual(policy[0]['receipt_threshold'],2000)
   personal=c.get('/ai/expense-report?scope=personal',headers={'X-Demo-User':'maya@northstar.demo'})
   self.assertEqual(personal.json()['metrics']['count'],0)
 def test_http_contract(self):
  def handler(req):
   self.assertEqual(req.url.path,'/execute')
   return httpx.Response(200,json={'answer':'test','provider':'rag','sources':['test']})
  provider=HTTPProvider('rag','http://test',transport=httpx.MockTransport(handler))
  context=Context(role='employee',department='Sales',expense_count=0,total_amount=0,exception_count=0)
  response=asyncio.run(provider.execute(AIRequest(task='expense_summary'),context))
  self.assertEqual(response.provider,'rag')

class ExpenseIntelligence(unittest.TestCase):
 def test_finance_report_and_filters(self):
  with TestClient(app) as c:
   h={'X-Demo-User':'devika@northstar.demo'}
   r=c.get('/ai/expense-report',headers=h)
   self.assertEqual(r.status_code,200,r.text)
   data=r.json()
   self.assertEqual(data['metrics']['count'],4)
   self.assertEqual(data['metrics']['total'],20110)
   self.assertEqual(data['metrics']['exceptions'],1)
   self.assertEqual(sum(x['amount'] for x in data['categories']),20110)
   self.assertEqual(data['exceptions'][0]['merchant'],'Uber')
   finding = data['insights'][0]
   self.assertEqual(finding['expense_id'], data['exceptions'][0]['id'])
   self.assertEqual(finding['detail'], data['exceptions'][0]['reason'])
   self.assertIn('submitter', finding['recommendation'])
   category = next(item['category'] for item in data['insights'] if item['kind'] == 'distribution')
   filtered = c.get('/ai/expense-report', headers=h, params={'category': category}).json()
   self.assertEqual([item['category'] for item in filtered['categories']], [category])
   self.assertFalse(any(item['kind'] == 'distribution' for item in filtered['insights']))
   self.assertEqual(c.get('/ai/expense-report?period_start=2026-11-18',headers=h).json()['metrics']['count'],2)
   self.assertEqual(c.get('/ai/expense-report?category=Hotel',headers=h).json()['metrics']['count'],1)
   self.assertEqual(c.get('/ai/expense-report?period_start=bad',headers=h).status_code,422)
   self.assertEqual(c.get('/ai/expense-report?period_start=2026-12-01&period_end=2026-11-01',headers=h).status_code,422)
 def test_report_role_scoping(self):
  with TestClient(app) as c:
   for name,count in [('aarav',2),('maya',2),('nisha',2),('devika',4)]:
    r=c.get('/ai/expense-report',headers={'X-Demo-User':name+'@northstar.demo'})
    self.assertEqual(r.status_code,200,r.text)
    self.assertEqual(r.json()['metrics']['count'],count)
    findings = [item for item in r.json()['insights'] if item['kind'] == 'attention']
    self.assertEqual(len(findings), 0 if name == 'nisha' else 1)
    if name == 'aarav':
     self.assertIn('attach', findings[0]['recommendation'])
    if name == 'maya':
     self.assertTrue(findings[0]['title'].startswith('Uber'))
