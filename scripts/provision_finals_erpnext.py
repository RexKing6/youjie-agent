"""Explicitly authorized local test Items/BOMs only; runtime adapter stays draft-only."""
import argparse
import json
from pathlib import Path
from urllib.request import Request,urlopen
from delivery_guard.integration import ERPNextConfig, ERPNextHttpClient
from delivery_guard.integration.finals_bridge import verify_bom

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--credential-file',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): parser.error('Preserve previous evidence')
    mapping=json.loads((ROOT/'data/integrations/finals_v2_mapping.json').read_text())
    config=ERPNextConfig.from_environment({'DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE':str(args.credential_file)})
    if config.public_host not in ('127.0.0.1','localhost') or config.environment!='test':
        raise ValueError('LOCAL_TEST_ONLY')
    client=ERPNextHttpClient(config)
    report={'authorization':'2026-09-17 explicit user: dedicated test Items and BOM native submission',
            'items':[],'boms':[],'old_records_modified':False,'stock_posting':False}
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for key in ('a1','a2','product'):
        code=mapping[key]
        if not code.startswith('YOUJIE-FINALS-'): raise ValueError('NAMESPACE')
        rows=client.list_documents('Item',fields=['name'],filters=[['item_code','=',code]])
        if not rows:
            client._request('POST','/api/resource/Item',payload={'doctype':'Item','item_code':code,
                'item_name':code,'item_group':'All Item Groups','stock_uom':'Nos','is_stock_item':1,
                'description':'YOUJIE-FINALS synthetic test data; no production equipment or stock posting'})
        doc=client.get_document('Item',code)
        if doc.get('stock_uom')!='Nos' or not doc.get('is_stock_item'): raise ValueError('EXISTING_ITEM_CONFLICT')
        report['items'].append({'name':doc['name'],'uom':doc['stock_uom'],'created':not rows})
        save()
    for quantity,a1,a2 in ((600,200,400),(400,200,200),(600,300,300)):
        allocation={'finished_quantity':quantity,'a1_total':a1,'a2':a2}
        rows=client.list_documents('BOM',fields=['name'],filters=[['item','=',mapping['product']]])
        matched=None
        for row in rows:
            doc=client.get_document('BOM',row['name'])
            try: verify_bom({**doc,'docstatus':1},mapping,allocation)
            except ValueError: continue
            matched=doc
            break
        if matched is None:
            matched=client._request('POST','/api/resource/BOM',payload={
                'doctype':'BOM','item':mapping['product'],'company':mapping['company'],
                'quantity':quantity,'is_active':1,'is_default':0,'with_operations':0,
                'rm_cost_as_per':'Valuation Rate','currency':'CNY','conversion_rate':1,
                'items':[{'item_code':mapping['a1'],'qty':a1,'uom':'Nos','rate':0},
                         {'item_code':mapping['a2'],'qty':a2,'uom':'Nos','rate':0}]
            })['data']
        if not matched['name'].startswith('BOM-YOUJIE-FINALS-'): raise ValueError('BOM_NAMESPACE')
        if matched['docstatus']==0:
            # Dedicated operator provisioning, not expanded runtime permissions.
            verify_bom({**matched,'docstatus':1},mapping,allocation)
            request=Request(config.base_url.rstrip('/')+'/api/method/frappe.client.submit',
                method='POST',data=json.dumps({'doc':json.dumps(matched)}).encode(),
                headers={'Content-Type':'application/json','Authorization':f'token {config.api_key}:{config.api_secret}'})
            with urlopen(request,timeout=30) as response:
                json.load(response)
        verified=client.get_document('BOM',matched['name'])
        verify_bom(verified,mapping,allocation)
        report['boms'].append({'name':verified['name'],'docstatus':verified['docstatus'],'allocation':allocation})
        save()
    report['passed']=True
    save()
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__': main()
