import asyncio, os, unittest
import json
from unittest.mock import patch
import httpx
from pathlib import Path
from test_release import app
from fastapi.testclient import TestClient
from app.ai.providers import HTTPProvider
from app.ai.contracts import AIRequest, Context
from app.ai.receipt_extraction import extract_receipt, parse_receipt
from app.ai.azure_receipts import extract_azure, normalize_result

class AIFoundation(unittest.TestCase):
 def test_policy_search_forwards_query_and_returns_evidence(self):
  async_client = httpx.AsyncClient

  def retrieve(request):
   self.assertEqual(str(request.url), 'http://127.0.0.1:8001/api/v1/retrieve')
   self.assertEqual(json.loads(request.content), {
       'user_query': 'Mumbai hotel cap for l3?', 'top_k': 3, 'grade': 'L3',
   })
   return httpx.Response(200, json={'status': 'OK', 'results': [{
       'chunk_id': 'hotel-1', 'policy_ref': 'HOTEL#1', 'title': 'Mumbai hotel cap',
       'text': 'The January cap is INR 10,925.', 'rerank_score': 0.99,
   }]})

  with TestClient(app) as client, patch.dict(os.environ, {
      'AI_ENABLED': 'true', 'POLICY_AGENT_URL': 'http://127.0.0.1:8001/',
  }), patch('app.ai.routes.httpx.AsyncClient', side_effect=lambda **kwargs: async_client(
      transport=httpx.MockTransport(retrieve), **kwargs,
  )) as upstream:
   payload = {'query': ' Mumbai hotel cap for l3? '}
   with self.assertLogs('uvicorn.error.policy_search', level='INFO') as logs:
    response = client.post('/ai/policy-search', json=payload)
   self.assertEqual(response.status_code, 200, response.text)
   self.assertEqual(response.json()['results'][0]['policy_ref'], 'HOTEL#1')
   trace_id = response.json()['trace_id']
   self.assertRegex(trace_id, r'^[0-9a-f]{32}$')
   self.assertIn(f'trace={trace_id}', logs.output[0])
   self.assertIn('grade=L3', logs.output[0])
   self.assertIn('"rerank_score": 0.99', logs.output[0])
   self.assertEqual(client.post('/ai/policy-search', json={'query': ' '}).status_code, 422)
   self.assertEqual(client.post('/ai/policy-search', json=payload, headers={
       'X-Demo-User': 'unknown',
   }).status_code, 401)
   self.assertEqual(upstream.call_count, 1)

 def test_policy_evaluation_rejects_invalid_stay_order(self):
  with TestClient(app) as client, patch.dict(os.environ, {'AI_ENABLED': 'true'}):
   for check_out in ('2026-11-14', '2026-11-15'):
    with self.subTest(check_out=check_out):
     response = client.post('/ai/policy-evaluations', json={
         'user_query': 'Can I claim this hotel expense?',
         'structured_inputs': {'travel_dates': {'start_date': '2026-11-15', 'end_date': check_out}},
     })
     self.assertEqual(response.status_code, 422)
     detail = response.json()['detail'][0]
     self.assertEqual(detail['loc'][-1], 'end_date')
     self.assertIn('Check-out must be after check-in.', detail['msg'])

 def test_policy_evaluation_mock_reuses_session_and_returns_unique_request_ids(self):
  headers = {'X-Demo-User': 'aarav@northstar.demo'}
  payload = {'user_query': 'Can I claim a hotel?', 'structured_inputs': {
      'travel_destination': 'Bengaluru', 'expense_amount': {'value': '18400', 'currency': 'INR'},
  }}
  with TestClient(app) as client, patch.dict(os.environ, {'AI_ENABLED': 'true'}):
   before = client.get('/expenses', headers=headers).json()
   first = client.post('/ai/policy-evaluations', headers=headers, json=payload)
   self.assertEqual(first.status_code, 200, first.text)
   first = first.json()
   self.assertEqual(first['decision_category'], 'NEEDS_INFORMATION')
   self.assertEqual(first['missing_required_fields'], ['travel_dates.start_date', 'travel_dates.end_date'])
   payload['session_id'] = first['session_id']
   payload['structured_inputs']['travel_dates'] = {'start_date': '2026-11-15', 'end_date': '2026-11-17'}
   followup = client.post('/ai/policy-evaluations', headers=headers, json=payload).json()
   self.assertEqual(followup['session_id'], first['session_id'])
   self.assertNotEqual(followup['request_id'], first['request_id'])
   self.assertEqual(followup['decision_category'], 'SOFT_FLAG')
   self.assertEqual(followup['allowed_expense_amount'], {'value': '16000', 'currency': 'INR'})
   self.assertEqual(followup['required_approval_level'], 'LINE_MANAGER')
   for amount in ('1400', '16000'):
    with self.subTest(amount=amount):
     payload['structured_inputs']['expense_amount']['value'] = amount
     within_limit = client.post('/ai/policy-evaluations', headers=headers, json=payload).json()
     self.assertEqual(within_limit['decision_category'], 'WITHIN_LIMIT')
     self.assertEqual(within_limit['allowed_expense_amount'], {'value': '16000', 'currency': 'INR'})
     self.assertFalse(within_limit['requires_human_approval'])
   payload['structured_inputs']['travel_destination'] = 'Other city'
   review = client.post('/ai/policy-evaluations', headers=headers, json=payload).json()
   self.assertEqual(review['decision_category'], 'HUMAN_REVIEW')
   self.assertIsNone(review['allowed_expense_amount'])
   self.assertEqual(client.get('/expenses', headers=headers).json(), before)
   self.assertEqual(client.post('/ai/policy-evaluations', headers={'X-Demo-User': 'unknown'},
                                json=payload).status_code, 401)

 def test_currency_codes_need_monetary_context(self):
  invoice = '3 CAD Hospitality LLP\nInvoice Date: 18 Dec 2023\nTotal ₹263.00'
  self.assertEqual(parse_receipt(invoice).fields.amount, 263)
  for marker in ('Currency CAD', 'Total CAD 263.00', 'Total 263.00 CAD'):
   with self.subTest(marker=marker):
    self.assertIsNone(parse_receipt(invoice + '\n' + marker).fields.amount)

 def test_azure_preview_completes_missing_details_with_matching_local_total(self):
  def azure_preview():
   return normalize_result({'analyzeResult': {
       'content': 'LODGING RECEIPT',
       'documents': [{'fields': {'Total': {'confidence': .98, 'valueCurrency': {'amount': 600, 'currencyCode': 'INR'}}}}],
   }})
  with TestClient(app) as client, patch.dict(os.environ, {'RECEIPT_EXTRACTION_MODE':'azure','AI_ENABLED':'true'}):
   files = {'file': ('example.pdf', b'%PDF-1.4\nexample')}
   for total in (600, 601):
    fallback = parse_receipt(f'Example Travel\nInvoice Date: 08/08/2025\nGrand Total INR {total}')
    with patch('app.ai.routes.extract_azure', return_value=azure_preview()), patch(
        'app.ai.routes.extract_receipt', return_value=fallback):
     response = client.post('/ai/receipt-preview', files=files).json()
    self.assertEqual(response['provider'], 'azure')
    self.assertEqual(response['fields']['amount'], 600)
    self.assertEqual(response['fields']['category'], 'Hotel')
    self.assertEqual(response['fields']['merchant'], 'Example Travel' if total == 600 else None)
    self.assertEqual(response['fields']['expense_date'], '2025-08-08' if total == 600 else None)

 def test_azure_invoice_fields_category_and_document_count(self):
  fields = {
      'VendorName': {'confidence': .98, 'valueString': 'Example Hotel'},
      'InvoiceDate': {'confidence': .95, 'valueDate': '2026-11-20'},
      'InvoiceTotal': {'confidence': .98, 'valueCurrency': {'amount': 7952, 'currencyCode': 'INR'}},
  }
  analysis = {'content': 'Example Hotel\nLODGING RECEIPT', 'documents': [{'fields': fields}]}
  result = normalize_result({'analyzeResult': analysis}, 'azure-invoice')
  self.assertEqual((result.fields.merchant, result.fields.amount, result.fields.category),
                   ('Example Hotel', 7952, 'Hotel'))
  self.assertIn('no matching', normalize_result({'analyzeResult': {'documents': []}}).warning)
  self.assertIn('multiple documents', normalize_result({'analyzeResult': {'documents': [{}, {}]}}).warning)

 def test_azure_preview_falls_back_only_when_no_document_matched(self):
  empty = normalize_result({'analyzeResult': {'documents': []}})
  multiple = normalize_result({'analyzeResult': {'documents': [{}, {}]}})
  with TestClient(app) as client, patch.dict(os.environ, {'RECEIPT_EXTRACTION_MODE':'azure','AI_ENABLED':'true'}):
   with patch('app.ai.routes.extract_azure', side_effect=[empty, multiple]), patch(
       'app.ai.routes.extract_receipt', return_value=parse_receipt('MEAL RECEIPT')) as local:
    files = {'file': ('sample.pdf', b'%PDF-1.4\nexample')}
    result = client.post('/ai/receipt-preview', files=files).json()
    self.assertEqual((result['provider'], result['fields']['category']), ('local', 'Meals'))
    result = client.post('/ai/receipt-preview', files=files).json()
    self.assertIn('multiple documents', result['warning'])
    self.assertEqual(local.call_count, 1)

 def test_travel_invoice_layouts_preserve_issuer_and_tax_inclusive_total(self):
  travel = parse_receipt('Booking ID\nTRAVEL (INDIA) PRIVATE LIMITED\nInvoice Date: 08/08/2025\n'
                         'Hotel Name    City\nAccommodation Charges\nGrand Total INR 3952.95')
  self.assertEqual((travel.fields.merchant, travel.fields.category), ('TRAVEL (INDIA) PRIVATE LIMITED', 'Hotel'))
  flight = parse_receipt('Tax Invoice    Sample Aviation Limited\nDate: 06/10/2023\n'
                         'PNR: Example    Flight No: EX-1\nCurrency: INR\nTax     Total(Incl\n'
                         'Grand Total     12.00     15.00     27.00')
  self.assertEqual((flight.fields.amount, flight.fields.category), (27, 'Airfare'))
  self.assertIsNone(parse_receipt('Date: 06/10/2023\nCurrency: INR\n'
                                  'Grand Total     12.00     15.00     27.00').fields.amount)
  receipt = parse_receipt('Date of issue: Sat, 4 Jan, 2025    Invoice issued by: Example Pvt Ltd\n'
                          'GSTIN: 27AABCB3428P1ZF\nTotal Amount before Tax : 127.12\n'
                          'Total Amount : GST : 22.88\nTotal Amount after Tax :\n150.00')
  self.assertEqual((receipt.fields.merchant, str(receipt.fields.expense_date), receipt.fields.amount),
                   ('Example Pvt Ltd', '2025-01-04', 150))

 def test_invoice_tables_and_date_priority(self):
  invoice = parse_receipt(
      'Sample Furnishings Limited     Tax Invoice\nGSTIN: 06AABCW7791A1ZB\n'
      'Order Date: Dec 20,2025\nInvoice Date: Dec 28, 2025\nTotal Amount    7  10348')
  self.assertEqual((invoice.fields.merchant, str(invoice.fields.expense_date), invoice.fields.amount),
                   ('Sample Furnishings Limited', '2025-12-28', 10348))
  voucher = parse_receipt('Date of Supply: 21/02/2026\nParticulars  Amount (Rs.)\n10000.00\n'
                          'Total Amount: Rs. Ten Thousand Only\nSample Education Private Limited')
  self.assertEqual((str(voucher.fields.expense_date), voucher.fields.amount), ('2026-02-21', 10000))
  till = parse_receipt('Date:06-11-2025\nTotal Qty       Grand Total\n  1     INR 1,999.00\nCash 2,000.00')
  self.assertEqual(till.fields.amount, 1999)
  courier = parse_receipt('Invoice Date: 30-Apr-2025\nTotal Amount % 293.34\n'
                          'Discount Amount -€0.00\nGSTIN: 29AAGCR8772D1ZY')
  self.assertEqual((str(courier.fields.expense_date), courier.fields.amount), ('2025-04-30', 293.34))

 def test_azure_receipt_provider_validates_confidence_currency_and_polling_origin(self):
  fields = {
      'MerchantName': {'confidence': .96, 'valueString': 'Example Store'},
      'TransactionDate': {'confidence': .6, 'valueDate': '2025-09-30'},
      'Total': {'confidence': .98, 'valueCurrency': {'amount': 600, 'currencyCode': 'INR'}},
  }
  payload = {'status':'succeeded', 'analyzeResult':{'documents':[{'fields':fields}]}}
  def transport(request):
   if request.method == 'POST':
    self.assertEqual(request.content, b'sample')
    return httpx.Response(202, headers={'Operation-Location':'https://example.test/result'})
   return httpx.Response(200, json=payload)
  config = {'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT':'https://example.test',
            'AZURE_DOCUMENT_INTELLIGENCE_KEY':'test'}
  with patch.dict(os.environ, config):
   preview = asyncio.run(extract_azure(b'sample', transport=httpx.MockTransport(transport)))
   with self.assertRaises(ValueError):
    asyncio.run(extract_azure(b'sample', transport=httpx.MockTransport(lambda request:
     httpx.Response(202, headers={'Operation-Location':'https://different.test/result'}))))
  self.assertEqual(preview.fields.amount, 600)
  self.assertIsNone(preview.fields.expense_date)
  fields['Total']['valueCurrency']['currencyCode'] = 'GBP'
  self.assertIsNone(normalize_result(payload).fields.amount)

 def test_retail_invoice_reads_invoice_value_but_excludes_tax_total(self):
  preview = parse_receipt(
   'Example Retail Limited (trading as Example)\nTAX INVOICE\n'
   'Date and Time:   30/09/2025 07:01 PM    Shipping information\n'
   'Payment Mode:  Pre-Paid    Invoice Value :    INR.12999.0\n'
   'Total Tax Amount: INR.1982.90'
  )
  self.assertEqual((preview.fields.merchant, preview.fields.amount, str(preview.fields.expense_date)),
                   ('Example Retail Limited (trading as Example)', 12999, '2025-09-30'))

 def test_receipt_image_layout_fallback_and_watermarked_headers(self):
  primary = 'SAMPLE ONLY - NOT VALID\nSample Fuel Station\nPune, India\nFUEL RECEIPT\nDate\nCurrency'
  fallback = primary.split('\nDate')[0] + '\nDate 2026-11-21\nTOTAL INR 1,254.00'
  with patch('app.ai.receipt_extraction.run_text', side_effect=[primary, fallback]):
   result = extract_receipt(b'image', '.jpg').fields
  self.assertEqual((result.merchant, result.amount, str(result.expense_date), result.category),
                   ('Sample Fuel Station', 1254, '2026-11-21', 'Fuel'))
  hotel = parse_receipt('SAMPLE ONLY - NOT VALID\nSample Hotel\nMumbai, India\nLODGING RECEIPT\nDate 2026-11-20\nTOTAL INR 7,952.00')
  self.assertEqual((hotel.fields.merchant, hotel.fields.category), ('Sample Hotel', 'Hotel'))
  for heading, category in [('MEAL RECEIPT', 'Meals'), ('TRANSPORT RECEIPT', 'Ground transport'),
                            ('RAIL TRAVEL RECEIPT', 'Rail travel'), ('COFFEE RECEIPT', 'Meals')]:
   with self.subTest(heading=heading):
    self.assertEqual(parse_receipt(heading).fields.category, category)
  self.assertIsNone(parse_receipt('GENERIC RECEIPT').fields)

 def test_receipt_preview_handles_split_fields_and_retries_unusable_pdf_text(self):
  ocr_text = 'Supplier: Maple Cafe\nInvoice No. 19  Bill Date: 22 Nov 2026\nNet Payable\nINR 500.25'
  def read_text(command, *args):
   if command == 'pdftotext':
    return 'Scanned document'
   if command == 'pdftoppm':
    Path(args[-1] + '-1.png').touch()
    Path(args[-1] + '-2.png').touch()
    return ''
   return ocr_text if args[0].endswith('-1.png') else 'Thank you'
  with patch('app.ai.receipt_extraction.run_text', side_effect=read_text) as run:
   preview = extract_receipt(b'%PDF-1.4', '.pdf')
  self.assertEqual([call.args[0] for call in run.call_args_list], ['pdftotext', 'pdftoppm', 'tesseract', 'tesseract'])
  self.assertEqual((preview.fields.merchant, str(preview.fields.expense_date), preview.fields.amount),
                   ('Maple Cafe', '2026-11-22', 500.25))
  self.assertIn('No readable text', parse_receipt('').warning)
  self.assertIn('Receipt text was found', parse_receipt('Unrecognized header').warning)
  invoice = parse_receipt('11/24/26, 9:37 AM Sample Store\nGSTIN\nINVOICE NO. X349 22/11/2026 20:47:55\nCGST SGST\nTotal Invoice Amount: 698.00\nTotal Received Amount 698.00')
  self.assertEqual((invoice.fields.merchant, str(invoice.fields.expense_date), invoice.fields.amount),
                   ('Sample Store', '2026-11-22', 698))

 def test_receipt_parser_uses_the_total_and_leaves_uncertain_values_empty(self):
  receipt = 'Maple Cafe\nReceipt date: 22/11/2026\nSubtotal INR 460.00\nGrand Total INR 500.25'
  fields = parse_receipt(receipt).fields
  self.assertEqual((fields.merchant, str(fields.expense_date), fields.amount),
                   ('Maple Cafe', '2026-11-22', 500.25))
  self.assertIsNone(parse_receipt(receipt + '\nTotal paid INR 600').fields.amount)
  self.assertIsNone(parse_receipt(receipt.replace('INR', '')).fields.amount)
  foreign = parse_receipt(receipt.replace('INR', 'USD'))
  self.assertIsNone(foreign.fields.amount)
  self.assertIn('Foreign currency', foreign.warning)

 def test_receipt_preview_is_read_only_and_matches_fixture_content(self):
  fixture = Path(__file__).resolve().parents[1] / 'app' / 'demo_receipts' / 'lemon-tree-demo.pdf'
  with TestClient(app) as client, patch.dict(os.environ, {'RECEIPT_EXTRACTION_MODE':'mock','AI_ENABLED':'true'}):
   headers = {'X-Demo-User':'aarav@northstar.demo'}
   before = client.get('/expenses', headers=headers).json()
   response = client.post('/ai/receipt-preview', headers=headers,
                          files={'file': ('renamed.pdf', fixture.read_bytes(), 'application/pdf')})
   self.assertEqual(response.status_code, 200, response.text)
   self.assertEqual(response.json(), {'provider':'mock', 'warning':None, 'fields':{
       'merchant':'Lemon Tree', 'amount':12600, 'expense_date':'2026-11-16', 'category':'Hotel'}})
   response = client.post('/ai/receipt-preview', headers=headers,
                          files={'file': (fixture.name, b'%PDF-1.4\nunknown', 'application/pdf')})
   self.assertIsNone(response.json()['fields'])
   bad_file = {'file': ('invalid.pdf', b'invalid', 'application/pdf')}
   self.assertEqual(client.post('/ai/receipt-preview', headers=headers, files=bad_file).status_code, 400)
   self.assertEqual(client.post('/ai/receipt-preview', headers={'X-Demo-User':'unknown'},
                                files=bad_file).status_code, 401)
   with patch.dict(os.environ, {'AI_ENABLED':'false'}):
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
