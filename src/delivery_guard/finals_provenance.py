"""Non-secret runtime identity and local run evidence. No credential inspection."""
from copy import deepcopy
import hashlib
from pathlib import Path
from delivery_guard.hashing import stable_hash


def runtime_provenance(registry: dict, model_name: str) -> dict:
    package=Path(__file__).resolve().parent
    files={str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(package.rglob("*.py"))}
    material={"schema":"finals_runtime/v1","source_sha256":files,
              "registry_sha256":stable_hash(registry),"model_name":model_name}
    return {**material,"runtime_hash":stable_hash(material)}


def assert_same_runtime(state: dict, current: dict) -> None:
    original=state.get("runtime_provenance")
    if not original:
        raise ValueError("RUN_PROVENANCE_MISSING_READ_ONLY: 历史任务仅可查看或导出，请新建任务")
    if original.get("runtime_hash") != current.get("runtime_hash"):
        raise ValueError("RUN_RUNTIME_CHANGED_READ_ONLY: 代码、资料或模型版本已变化，请新建任务，不沿用旧审批")


def export_evidence(state: dict, current: dict, journal: dict | None = None) -> dict:
    def validate(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.lower() in {"api_key","api_secret","password","authorization","access_token","session_capability"}:
                    raise ValueError("CREDENTIAL_SHAPED_FIELD_EXPORT_BLOCKED")
                validate(item)
        elif isinstance(value,list):
            for item in value: validate(item)
    validate(state)
    compatible=True
    try: assert_same_runtime(state,current)
    except ValueError: compatible=False
    return {"schema":"finals_run_evidence/v2","state_sha256":stable_hash(state),"state":deepcopy(state),
            "runtime_compatible":compatible,"export_runtime_hash":current["runtime_hash"],"journal":journal,
            "disclosure":"本地任务证据，不是公开发布。版本hash用于复核而非真实性签名；键名检查不能替代人工隐私审查。业务模拟与真实系统结果以本run记录分别标注。"}
