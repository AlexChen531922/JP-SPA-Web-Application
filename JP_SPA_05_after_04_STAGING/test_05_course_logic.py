"""Pure logic checks for the 05 patch; no production database required."""
import ast
import json
import sys
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from types import ModuleType
from importlib.util import spec_from_file_location, module_from_spec

P = (Path.cwd()/'project' if (Path.cwd()/'project'/'course_entitlements.py').is_file()
     else Path(__file__).resolve().parents[1]/'updated'/'project')

# Load the helper without requiring a real Flask or MySQL installation.
project = ModuleType('project'); project.__path__ = [str(P)]
sys.modules['project'] = project
wallet = ModuleType('project.stored_value')
wallet.money = lambda value: Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
sys.modules['project.stored_value'] = wallet
spec = spec_from_file_location('project.course_entitlements', P/'course_entitlements.py')
ent = module_from_spec(spec); sys.modules[spec.name]=ent; spec.loader.exec_module(ent)
assert ent.parse_tiers('5:11000, 10:20000') == {5:Decimal('11000'),10:Decimal('20000')}
for bad in ('1:100','5:-10','5:0','5:100,5:101','3:1.234','101:1000','bad','5:10,'):
    try:ent.parse_tiers(bad)
    except ValueError:pass
    else:raise AssertionError('bad tier accepted: '+bad)
assert ent.available_sessions(dict(total_sessions=10,completed_sessions=6,reserved_sessions=2)) == 2
assert ent.available_sessions(dict(total_sessions=10,completed_sessions=6,reserved_sessions=4)) == 0

class Cursor:
    def __init__(self):
        self.purchase={'id':5,'customer_id':7,'course_id':11,'total_sessions':3,
                      'total_paid':Decimal('10000.01'),'completed_sessions':0,
                      'reserved_sessions':0}
        self.alloc={};self.result=None;self.rowcount=1;self.events=[];self.statements=[]
    def execute(self,sql,args=()):
        self.statements.append((sql,args));sql=' '.join(sql.split())
        if 'SELECT id,customer_id,course_id,total_sessions' in sql:
            self.result=self.purchase.copy()
        elif 'SELECT a.id,a.purchase_id,a.status' in sql:
            bid=args[0];self.result=self.alloc.get(bid,{}).copy() or None
        elif 'SELECT id,total_sessions,total_paid' in sql:
            self.result=self.purchase.copy()
        elif 'SELECT COALESCE(SUM(a.recognized_amount),0)' in sql:
            self.result={'recognized':sum((x['recognized_amount'] for x in self.alloc.values() if x['status']=='completed'),Decimal(0))}
        elif sql.startswith('INSERT INTO customer_course_allocations'):
            purchase_id,bid,actor=args
            if bid in self.alloc:raise Exception('duplicate booking allocation')
            self.alloc[bid]=dict(id=bid,purchase_id=purchase_id,status='reserved',recognized_amount=Decimal(0))
        elif sql.startswith('INSERT INTO customer_course_events'):
            self.events.append(args)
        elif sql.startswith('UPDATE customer_course_purchases SET reserved_sessions=reserved_sessions+1'):
            self.purchase['reserved_sessions']+=1
        elif sql.startswith('UPDATE customer_course_purchases SET reserved_sessions=reserved_sessions-1'):
            if self.purchase['reserved_sessions']>0:self.purchase['reserved_sessions']-=1;self.rowcount=1
            else:self.rowcount=0
        elif sql.startswith('UPDATE customer_course_purchases SET completed_sessions=completed_sessions+1'):
            self.purchase['completed_sessions']+=1;self.purchase['reserved_sessions']-=1
        elif "UPDATE customer_course_allocations SET status='completed'" in sql:
            amount,actor,bid=args;self.alloc[bid]['status']='completed';self.alloc[bid]['recognized_amount']=amount
        elif "UPDATE customer_course_allocations SET status='released'" in sql:
            actor,bid=args;self.alloc[bid]['status']='released'
        elif "UPDATE customer_course_allocations SET status='reserved'" in sql:
            actor,bid=args;self.alloc[bid]['status']='reserved'
        else:self.result=None
    def fetchone(self):return self.result

c=Cursor()
for bid in (101,102,103):
    ent.reserve_for_booking(c,5,7,11,bid,9)
assert c.purchase['reserved_sessions']==3
try:ent.reserve_for_booking(c,5,7,11,104,9)
except ValueError:pass
else:raise AssertionError('overbooking allowed')
# Cancel returns exactly one held session; restore reacquires it.
ent.transition_allocation(c,101,'cancelled',9)
assert c.purchase['reserved_sessions']==2 and c.alloc[101]['status']=='released'
ent.transition_allocation(c,101,'confirmed',9)
assert c.purchase['reserved_sessions']==3 and c.alloc[101]['status']=='reserved'
# Completing does not charge again; allocates price exactly once.
for bid in (101,102,103):
    assert ent.transition_allocation(c,bid,'completed',9) is True
assert c.purchase['completed_sessions']==3 and c.purchase['reserved_sessions']==0
assert sum((x['recognized_amount'] for x in c.alloc.values()),Decimal(0))==Decimal('10000.01')
assert [c.alloc[b]['recognized_amount'] for b in (101,102,103)] == [Decimal('3333.34'),Decimal('3333.34'),Decimal('3333.33')]
assert ent.transition_allocation(c,101,'completed',9) is True
try:ent.transition_allocation(c,101,'cancelled',9)
except ValueError:pass
else:raise AssertionError('completed entitlement reverted without correction')
assert [x[2] for x in c.events].count('complete')==3

# Server payment line validation (extract exact implementation, no Flask imports).
src=ast.parse((P/'course_sales.py').read_text())
node=next(n for n in src.body if isinstance(n,ast.FunctionDef) and n.name=='_payments')
namespace={'json':json,'money':wallet.money,'Decimal':Decimal,
           '_ALLOWED_METHODS':{'cash','credit_card','bank_transfer','stored_value','other'}}
exec(compile(ast.Module(body=[node],type_ignores=[]),'<payments>','exec'),namespace)
fun=namespace['_payments']
assert fun(json.dumps([{'method':'cash','amount':'600'},{'method':'credit_card','amount':'400'}]),Decimal(1000)) == [('cash',Decimal(600)),('credit_card',Decimal(400))]
for input_data in (
    [{'method':'cash','amount':'900'}],
    [{'method':'deposit_credit','amount':'1000'}],
    [{'method':'stored_value','amount':'-1000'}],
    [{'method':'cash','amount':'1000.50'}]):
    try:fun(json.dumps(input_data),Decimal(1000))
    except ValueError:pass
    else:raise AssertionError('invalid payment accepted: '+repr(input_data))
print('PASS: tier pricing, remaining/reserved quantities, cancellation, restoration, last-cent rounding, paid-in-full mixed payments, and forbidden deposit credit.')
