from copy import deepcopy
import json

import pytest

from delivery_guard.finals_wiki import citation, compile_wiki, current_records, load_documents, qualify

ORDER = {"customer": "客户乙", "order_id": "O-208", "revision": "B", "quantity": 600, "a1_available": 200}
STOCK = {"batch": "B17", "on_hand": 500, "hold": 100, "reserved": 0, "revision": 1}


def docs(*ids):
    r = load_documents()
    return [r[i] for i in ids]


def qualification_docs(*ids):
    """Known current technical fixture plus explicitly specified approval/QC."""
    return docs(*ids,"TECH-CURRENT")


def test_current_order_requires_customer_and_quality_evidence():
    q = qualify(ORDER, qualification_docs("AP-CURRENT", "QC-PASS"), STOCK)
    assert q["eligible_a2"] == 400
    assert q["verified_material_total"] == 600
    assert q["gaps"] == []


@pytest.mark.parametrize("ids,gap", [
    (("AP-OTHER", "QC-PASS"), "approval_missing"),
    (("CHAT-01", "MINUTES-01", "QC-PASS"), "approval_missing"),
    (("AP-CURRENT",), "quality_missing"),
    (("AP-CURRENT", "QC-WAIT"), "quality_pending"),
    (("AP-CURRENT", "AP-DENY", "QC-PASS"), "approval_conflict"),
    (("AP-CURRENT", "AP-PARTIAL", "QC-PASS"), "approval_conflict"),
    (("AP-CURRENT", "QC-PASS", "QC-WAIT"), "quality_conflict"),
    (("AP-DENY", "QC-PASS"), "approval_denied"),
])
def test_unknown_or_conflicting_never_releases(ids, gap):
    q = qualify(ORDER, docs(*ids), STOCK)
    assert gap in q["gaps"]
    assert q["eligible_a2"] == 0


def test_different_customer_not_same_scope_conflict():
    wiki = compile_wiki(docs("AP-CURRENT", "AP-OTHER"))
    assert not wiki["conflicts"]
    assert qualify(ORDER, qualification_docs("AP-CURRENT", "AP-OTHER", "QC-PASS"), STOCK)["eligible_a2"] == 400


def test_explicit_authorized_supersession():
    d = qualification_docs("AP-CURRENT", "AP-DENY", "AP-RESOLVE", "QC-WAIT", "QC-RELEASE")
    assert qualify(ORDER, d, STOCK)["eligible_a2"] == 400
    assert not compile_wiki(d)["conflicts"]


@pytest.mark.parametrize("target",["NONEXISTENT","QC-PASS","AP-RESOLVE"])
def test_supersession_cannot_hide_missing_wrong_role_or_self_target(target):
    d=qualification_docs("AP-CURRENT","AP-DENY","AP-RESOLVE","QC-PASS")
    record=next(x for x in d if x["id"]=="AP-RESOLVE")
    import re
    record["body"]=re.sub(r"明确替代：[^\n]+", "明确替代："+target,record["body"])
    with pytest.raises(ValueError): compile_wiki(d)


@pytest.mark.parametrize("field,value", [("客户", "客户甲"), ("订单", "O-999"), ("版本", "C"), ("批次", "B18"), ("物料", "A3"), ("替代", "A0")])
def test_each_scope_dimension_enforced(field, value):
    d = qualification_docs("AP-CURRENT", "QC-PASS")
    original = {"客户": "客户乙", "订单": "O-208", "版本": "B", "批次": "B17", "物料": "A2", "替代": "A1"}[field]
    d[0]["body"] = d[0]["body"].replace(f"{field}：{original}", f"{field}：{value}")
    assert qualify(ORDER, d, STOCK)["eligible_a2"] == 0


@pytest.mark.parametrize("cap,hold,expected", [(300, 100, 300), (400, 200, 300), (100, 0, 100), (400, 500, 0)])
def test_quantity_and_stock_are_hard_constraints(cap, hold, expected):
    d = qualification_docs("AP-CURRENT", "QC-PASS")
    d[0]["body"] = d[0]["body"].replace("数量上限：400", f"数量上限：{cap}")
    q = qualify(ORDER, d, {**STOCK, "hold": hold})
    assert q["eligible_a2"] == expected


def test_untrusted_issuer_cannot_grant_approval():
    d = docs("AP-CURRENT", "QC-PASS")
    d[0]["role"] = "supplier"
    assert qualify(ORDER, d, STOCK)["eligible_a2"] == 0


def test_sources_and_citations_stable_and_literal():
    d = docs("AP-CURRENT", "QC-PASS", "CHAT-01")
    w = compile_wiki(d)
    assert w["version"] == compile_wiki(deepcopy(d))["version"]
    assert w["conflicts"][0]["kind"] == "unverified_generalization"
    for claim in w["claims"]:
        c = claim["citation"]
        body = next(x["body"] for x in d if x["id"] == c["document_id"])
        assert body[c["start"]:c["end"]] == c["quote"]
    with pytest.raises(ValueError):
        citation(d[0], "虚构的引用")


def test_invalid_supersession_and_duplicate_fields_fail():
    d = docs("AP-CURRENT", "AP-OTHER")
    d[0]["body"] += "\n明确替代：AP-OTHER"
    with pytest.raises(ValueError):
        current_records(d, "customer_authority")
    d = docs("AP-CURRENT")
    d[0]["body"] += "\n数量上限：999"
    with pytest.raises(ValueError):
        compile_wiki(d)


def test_multi_document_supersession_cycle_cannot_erase_conflict():
    d = docs("AP-CURRENT", "AP-DENY")
    d[0]["body"] += "\n明确替代：AP-DENY"
    d[1]["body"] += "\n明确替代：AP-CURRENT"
    with pytest.raises(ValueError, match="Cyclic supersession"):
        current_records(d, "customer_authority")


def test_model_summary_is_only_a_proposal():
    class Fake:
        mode, model_name = "test_double", "fake"
        def complete_structured(self, **kwargs):
            return kwargs["schema"].model_validate({"claims": [{"document_id": "AP-CURRENT", "quote": "客户：客户乙", "summary": "错误摘要：无限量批准"}]})
    d = docs("AP-CURRENT", "QC-PASS")
    with pytest.raises(ValueError):
        compile_wiki(d, Fake())
    assert qualify(ORDER, d + docs("TECH-CURRENT"), STOCK)["eligible_a2"] == 400


def test_customer_approval_does_not_replace_current_technical_confirmation():
    q=qualify(ORDER,docs("AP-CURRENT","QC-PASS","MINUTES-01"),STOCK)
    assert "technical_missing" in q["gaps"] and q["eligible_a2"]==0


@pytest.mark.parametrize("summary", ["工程师确认A1在客户甲B版产品中具备技术可用性。", "A1替代A2已经可用。", "A99具备技术可用性。"])
def test_literal_quote_does_not_excuse_wrong_material_summary(summary):
    class Fake:
        mode, model_name = "test_double", "wrong-material"
        def complete_structured(self, **kwargs):
            doc = json.loads(kwargs["user_text"])[0]
            return kwargs["schema"](claims=[{"document_id": doc["id"], "quote": doc["body"], "summary": summary}])
    with pytest.raises(ValueError):
        compile_wiki(docs("MINUTES-01"), Fake())


def test_material_direction_guard_is_source_relative_not_hardcoded_a2():
    from delivery_guard.finals_wiki import validate_summary_material_direction
    doc = docs("MINUTES-01")[0]
    doc["body"] = doc["body"].replace("A2", "R47").replace("A1", "R18")
    validate_summary_material_direction(doc, "R47替代R18，在客户甲B版产品中具备技术可用性。")
    with pytest.raises(ValueError):
        validate_summary_material_direction(doc, "R18在客户甲B版产品中具备技术可用性。")


@pytest.mark.parametrize("summary", ["客户甲批准订单O-208使用A2。", "客户乙已批准订单O-107。", "A2批次B99允许使用。"])
def test_summary_cannot_import_neighbor_document_identifiers(summary):
    from delivery_guard.finals_wiki import validate_summary_material_direction
    with pytest.raises(ValueError):
        validate_summary_material_direction(docs("AP-OTHER")[0], summary)


def test_extractive_summary_keeps_procurement_question_visibly_non_authoritative():
    class Extractor:
        mode, model_name = "test_double", "extract-only"
        def complete_structured(self, **kwargs):
            doc = json.loads(kwargs["user_text"])[0]
            return kwargs["schema"](selections=[{"document_id": doc["id"], "document_hash":doc["document_hash"],
                                                "span_ids":[doc["spans"][-1]["span_id"]]}])
    w = compile_wiki(docs("CHAT-01"), Extractor())
    c = w["claims"][0]
    assert "采购沟通（非客户或质量批准）" in c["summary"]
    assert c["model_selected_excerpt"] == c["summary_citation"]["quote"]


@pytest.mark.parametrize("attack,code", [("missing", "WIKI_COVERAGE_MISSING"),
    ("duplicate", "WIKI_DUPLICATE_SOURCE"), ("hash", "WIKI_SOURCE_HASH_MISMATCH"),
    ("cross_source", "SPAN_NOT_FOUND"), ("duplicate_span", "WIKI_DUPLICATE_SPAN")])
def test_source_selection_contract_rejects_incomplete_and_forged(attack, code):
    class Selector:
        mode = "test_double"
        def complete_structured(self, **kwargs):
            sources = json.loads(kwargs["user_text"])
            rows = [{"document_id":d["id"], "document_hash":d["document_hash"],
                     "span_ids":[d["spans"][-1]["span_id"]]} for d in sources]
            if attack == "missing": rows.pop()
            if attack == "duplicate": rows.append(rows[0])
            if attack == "hash": rows[0]["document_hash"] = "forged"
            if attack == "cross_source": rows[0]["span_ids"] = rows[1]["span_ids"]
            if attack == "duplicate_span": rows[0]["span_ids"] *= 2
            return kwargs["schema"](selections=rows)
    with pytest.raises(ValueError, match=code):
        compile_wiki(docs("AP-CURRENT", "QC-PASS"), Selector())


def test_span_ids_change_with_revision_and_quotes_are_exact():
    from delivery_guard.finals_wiki import source_spans
    doc = docs("AP-CURRENT")[0]
    old = source_spans(doc)
    revised = deepcopy(doc)
    revised["body"] += "\n补充限制：暂停执行。"
    assert not ({x["span_id"] for x in old} & {x["span_id"] for x in source_spans(revised)})
    for span in old:
        assert doc["body"][span["start"]:span["end"]] == span["text"]
