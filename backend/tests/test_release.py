import os,tempfile,unittest
from pathlib import Path
TMP=tempfile.TemporaryDirectory()
os.environ['DATABASE_URL']='sqlite:///'+TMP.name+'/test.db'
os.environ['UPLOAD_DIR']=TMP.name+'/uploads'
from fastapi.testclient import TestClient
from app.main import app
class Release(unittest.TestCase):
 def test_workflow(self):
  with TestClient(app) as c:
   def h(name):return {'X-Demo-User':name+'@northstar.demo'}
   rows=c.get('/expenses',headers=h('devika')).json(); self.assertEqual(len(rows),4)
   by={x['merchant']:x for x in rows}; r=by['Lemon Tree']; n=by['Social']; u=by['Uber']; self.assertFalse(r['policy_flag']);self.assertFalse(n['policy_flag']);self.assertTrue(u['policy_flag']);self.assertEqual(n['policy_evaluation']['policy']['name'],'Manager standard')
   for x,magic in [(r,b'%PDF'),(n,b'\x89PNG')]:
    path=f"/expenses/{x['id']}/receipt"; self.assertTrue(c.get(path,headers=h('devika')).content.startswith(magic));self.assertEqual(c.get(path,headers=h('aarav')).status_code,404)
   self.assertEqual(c.get('/expenses',headers=h('nisha')).json()[0]['id'],r['id'])
   self.assertEqual(c.get('/finance/summary',headers=h('devika')).json()['exceptions'],1)
   self.assertEqual(c.post(f"/expenses/{u['id']}/request-receipt",headers=h('maya')).status_code,200)
   data=c.get(f"/expenses/{r['id']}/receipt",headers=h('devika')).content
   self.assertEqual(c.post(f"/expenses/{u['id']}/receipt",headers=h('aarav'),files={'file':('demo.pdf',data,'application/pdf')}).status_code,200)
   self.assertEqual(c.get('/finance/summary',headers=h('devika')).json()['exceptions'],0)
   self.assertEqual(c.post(f"/expenses/{u['id']}/reevaluate",headers=h('maya')).status_code,403)
   self.assertEqual(c.post(f"/expenses/{u['id']}/reevaluate",headers=h('devika')).status_code,200)
   self.assertEqual(c.patch(f"/expenses/{u['id']}",headers=h('aarav'),json={'amount':16000}).status_code,200)
   self.assertEqual(c.get('/finance/summary',headers=h('devika')).json()['exceptions'],1)
 def test_boundaries(self):
  from app.policy import evaluate
  p={'max_expense':15000,'receipt_threshold':2000}
  self.assertEqual(len(evaluate(2000,False,p)['violations']),0)
  self.assertEqual(len(evaluate(15001,False,p)['violations']),2)
  self.assertEqual(len(evaluate(15001,True,p)['violations']),1)
if __name__=='__main__':unittest.main()
