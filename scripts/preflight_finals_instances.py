"""Read-only, credential-redacted test-instance preflight. Never creates BOMs."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from delivery_guard.integration import ERPNextConfig, ERPNextHttpClient, OpenMESConfig, OpenMESHttpClient


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--erp-credential-file",type=Path,required=True)
    parser.add_argument("--mes-credential-file",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): parser.error("Preserve existing evidence")
    erp=ERPNextHttpClient(ERPNextConfig.from_environment({"DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE":str(args.erp_credential_file)}))
    mes=OpenMESHttpClient(OpenMESConfig.from_environment({"DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE":str(args.mes_credential_file)}))
    report={"observed_at":datetime.now(timezone.utc).isoformat(),"read_only":True,"external_writes":0,
            "erp":erp.health(),"mes":mes.health(),"items":{},"boms":[]}
    for code in ("YOUJIE-FINALS-A1","YOUJIE-FINALS-A2","YOUJIE-FINALS-PRODUCT"):
        rows=erp.list_documents("Item",fields=["name","item_code"],filters=[["item_code","=",code]])
        report["items"][code]="present" if rows else "missing"
    report["boms"]=erp.list_documents("BOM",fields=["name","docstatus","item","quantity"],filters=[["item","=","YOUJIE-FINALS-PRODUCT"]])
    report["material_ready"]=all(v=="present" for v in report["items"].values()) and any(b["docstatus"]==1 for b in report["boms"])
    report["scope"]="Health and master-data presence only; not end-to-end execution proof. Native BOM submission requires explicit separate permission."
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__": main()
