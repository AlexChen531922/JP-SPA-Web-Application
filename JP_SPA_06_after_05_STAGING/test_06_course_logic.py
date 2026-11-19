"""06 offline logic tests. No MySQL server is accessed."""
import ast
import importlib.util
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import ModuleType

ROOT = Path.cwd() / 'project'
assert ROOT.is_dir(), 'Run from JP-SPA-Web-Application root'
proj = ModuleType('project');proj.__path__ = [str(ROOT)]
sys.modules['project'] = proj
wallet = ModuleType('project.stored_value')
def money(v):
    n=Decimal(str(v));out=n.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    if out != n or not n.is_finite():raise ValueError('invalid money')
    return out
wallet.money=money
sys.modules['project.stored_value']=wallet
ent = ModuleType('project.course_entitlements')
def transition(cursor,booking_id,status,actor):
    assert status == 'completed'
    cursor.operations.append(('entitlement_complete',booking_id,actor))
ent.transition_allocation=transition
sys.modules['project.course_entitlements']=ent
spec=importlib.util.spec_from_file_location('project.course_service',ROOT/'course_service.py')
service=importlib.util.module_from_spec(spec);sys.modules[spec.name]=service;spec.loader.exec_module(service)

assert service.parse_materials(json.dumps([
 {'source':'store','inventory_id':20,'amount':'10.25'},
 {'source':'customer','inventory_id':10,'amount':'5'}])) == [
 ('customer',10,Decimal('5.00')),('store',20,Decimal('10.25'))]

for lines in [
 [{'source':'store','inventory_id':2,'amount':'0'}],
 [{'source':'store','inventory_id':2,'amount':'1.001'}],
 [{'source':'store','inventory_id':2,'amount':'-1'}],
 [{'source':'other','inventory_id':2,'amount':'1'}],
 [{'source':'store','inventory_id':2,'amount':'1'}, {'source':'customer','inventory_id':2,'amount':'2'}],
 [{'source':'store','inventory_id':0,'amount':'1'}],
 [{'source':'store','inventory_id':True,'amount':'1'}]
]:
    try:service.parse_materials(json.dumps(lines))
    except (ValueError,TypeError):pass
    else:raise AssertionError('Invalid materials allowed: '+str(lines))

class FakeCursor:
    def __init__(self,mode='mixed',status='confirmed',requires=1,balances=(Decimal('50'),Decimal('100'))):
        self.booking={'id':77,'customer_id':10,'status':status,
                      'course_purchase_id':7,'is_unpaid_course_booking':0,
                      'material_mode':mode,'requires_material_confirmation':requires,
                      'component_customer_value':Decimal('1700'),'uses_store_consumables':0}
        self.inv={10:dict(id=10,customer_id=10,remaining_amount=balances[0],capacity_unit='ml'),
                  20:dict(id=20,customer_id=99,remaining_amount=balances[1],capacity_unit='ml')}
        self.rowcount=1;self.lastrowid=100;self.result=None;self.operations=[]
    def execute(self,sql,args=()):
        normalized=' '.join(sql.split());self.operations.append((normalized,args))
        if normalized.startswith('SELECT b.id,b.customer_id,b.status'):
            self.result=self.booking.copy()
        elif normalized.startswith('SELECT id FROM users WHERE email'):
            self.result={'id':99}
        elif normalized.startswith('SELECT id,customer_id,remaining_amount,capacity_unit'):
            self.result=self.inv.get(args[0],{}).copy() or None
        elif normalized.startswith('UPDATE customer_inventory SET'):
            amount,inv_id,owner,minimum=args
            row=self.inv.get(inv_id)
            if not row or row['customer_id']!=owner or row['remaining_amount']<minimum:
                self.rowcount=0
            else:row['remaining_amount']-=amount;self.rowcount=1
        elif normalized.startswith('INSERT INTO'):
            self.lastrowid+=1
        else:self.result=None
    def fetchone(self):return self.result

c=FakeCursor()
summary=service.complete_course_booking(c,77,'test_request_key_012345678901',json.dumps([
 {'source':'customer','inventory_id':10,'amount':'5'},
 {'source':'store','inventory_id':20,'amount':'10'}]),1,'127.0.0.1')
assert summary['lines']==2
assert c.inv[10]['remaining_amount']==Decimal(45)
assert c.inv[20]['remaining_amount']==Decimal(90)
assert len([x for x in c.operations if x[0]=='entitlement_complete'])==1
assert len([x for x in c.operations if x[0].startswith('INSERT INTO customer_inventory_requests')])==2
assert len([x for x in c.operations if x[0].startswith('INSERT INTO customer_inventory_movements')])==2
assert len([x for x in c.operations if x[0].startswith('INSERT INTO course_service_materials')])==2

for mode,sources in [
 ('mixed',[{'source':'customer','inventory_id':10,'amount':'5'}]),
 ('store',[{'source':'customer','inventory_id':10,'amount':'5'}]),
 ('customer',[{'source':'store','inventory_id':20,'amount':'5'}])
]:
    try:service.complete_course_booking(FakeCursor(mode=mode),77,'test_request_key_012345678901',json.dumps(sources),1,'ip')
    except ValueError:pass
    else:raise AssertionError('Wrong material source permitted: '+mode)

try:service.complete_course_booking(FakeCursor(status='completed'),77,'test_request_key_012345678901','[]',1,'ip')
except ValueError:pass
else:raise AssertionError('Double completion permitted')

try:service.complete_course_booking(FakeCursor(balances=(Decimal('2'),Decimal('100'))),77,'test_request_key_012345678901',json.dumps([
 {'source':'customer','inventory_id':10,'amount':'5'},
 {'source':'store','inventory_id':20,'amount':'10'}]),1,'ip')
except ValueError:pass
else:raise AssertionError('Overdeduct permitted')

# Extract the real pricing helper without importing Flask, MySQL or decorators.
src=ast.parse((ROOT/'course_sales.py').read_text())
funcs=[n for n in src.body if isinstance(n,ast.FunctionDef) and n.name in ('_nonnegative_integer','_sale_components')]
ns={'Decimal':Decimal,'money':money}
exec(compile(ast.Module(body=funcs,type_ignores=[]),'<sale>','exec'),ns)
class PriceCursor:
    def execute(self,*args):pass
    def fetchone(self):return {'n':1}
fields={'material_mode':'mixed','hand_fee':'1600','store_product_fee':'1700','customer_product_value':'1700'}
assert ns['_sale_components'](fields,{'uses_store_consumables':0},1,10,PriceCursor()) == (
 'mixed',Decimal('1600'),Decimal('1700'),Decimal('1700'),1)
try:ns['_sale_components'](fields,{'uses_store_consumables':1},1,10,PriceCursor())
except ValueError:pass
else:raise AssertionError('Fixed-price bundle allowed customer materials')
assert ns['_sale_components'](fields,{'uses_store_consumables':0},5,10,PriceCursor())[0]=='store'
print('PASS 06: customer+shop mixed materials, source ownership and balance checks, one-time completion, customer product pricing, non-cash source valuation, bundle restriction.')
