"""Atomic local JSON snapshots; no database migrations or credential storage."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from delivery_guard.hashing import stable_hash


class FinalsStateStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lock=threading.RLock()

    def path(self, run_id: str) -> Path:
        if not re.fullmatch(r"finals_[a-f0-9]{32}",run_id):
            raise ValueError("INVALID_RUN_ID")
        return self.directory / (run_id+".json")

    def save(self, state: dict) -> None:
        with self.lock:
            self._save(state)

    def _journal(self,run_id: str) -> list[dict]:
        path=self.path(run_id).with_suffix(".journal.jsonl")
        if not path.exists(): return []
        rows=[]
        previous=None
        for line in path.read_text().splitlines():
            try:
                row=json.loads(line)
                content={k:v for k,v in row.items() if k!="entry_hash"}
                valid=(row["schema"]=="finals_journal/v1" and row["sequence"]==len(rows)+1
                       and row["previous_hash"]==previous and row["state"]["run_id"]==run_id
                       and row["state_hash"]==stable_hash(row["state"]) and row["entry_hash"]==stable_hash(content))
            except (ValueError,KeyError,TypeError):
                valid=False
            if not valid: raise ValueError("JOURNAL_INTEGRITY_FAILED")
            rows.append(row)
            previous=row["entry_hash"]
        return rows

    def journal_evidence(self,run_id: str) -> dict:
        with self.lock:
            rows=self._journal(run_id)
            return {"entries":len(rows),"head_hash":rows[-1]["entry_hash"] if rows else None,
                    "chain_valid":True,"scope":"local corruption/crash detection, not signed audit or multi-process locking"}

    def _save(self,state: dict) -> None:
        path = self.path(state["run_id"])
        envelope = {"schema":"finals_state/v2", "sha256":stable_hash(state), "state":state}
        rows=self._journal(state["run_id"])
        if not rows or rows[-1]["state_hash"]!=envelope["sha256"]:
            entry={"schema":"finals_journal/v1","sequence":len(rows)+1,
                   "previous_hash":rows[-1]["entry_hash"] if rows else None,
                   "state_hash":envelope["sha256"],"state":state}
            entry["entry_hash"]=stable_hash(entry)
            with path.with_suffix(".journal.jsonl").open("a",encoding="utf-8") as journal:
                journal.write(json.dumps(entry,ensure_ascii=False)+"\n")
                journal.flush()
                os.fsync(journal.fileno())
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",dir=self.directory,
                                         prefix=".pending-", suffix=".json",delete=False) as stream:
            json.dump(envelope,stream,ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
            pending=stream.name
        os.replace(pending,path)

    def load(self, run_id: str) -> dict:
        with self.lock:
            rows=self._journal(run_id)
            path=self.path(run_id)
            if path.exists():
                envelope=json.loads(path.read_text())
                state=envelope["state"]
                if envelope.get("schema")!="finals_state/v2" or stable_hash(state)!=envelope["sha256"] or state["run_id"]!=run_id:
                    raise ValueError("STATE_INTEGRITY_FAILED")
                if rows and envelope["sha256"] not in {r["state_hash"] for r in rows}:
                    raise ValueError("SNAPSHOT_JOURNAL_MISMATCH")
            elif not rows:
                raise FileNotFoundError(run_id)
            # The append is durable before snapshot replacement: recover a crash in between.
            return rows[-1]["state"] if rows else state
