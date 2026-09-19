"""Approval quantities are not order demand; synthetic development regressions."""
import json
import pytest
from delivery_guard.finals_agent import FinalsInvestigation, UserInterpretation, rule_interpret

TEXT = '找到本订单的技术确认和客户批准,允许使用300个A2,请核对附件。'

@pytest.mark.parametrize('text', [TEXT, '批准使用300件A2，请核对邮件。', '库存400个A2，采购100个A1。'])
def test_material_quantity_does_not_change_order(text):
    assert rule_interpret(text, True).quantity is None
    engine = FinalsInvestigation()
    run = engine.start('连接件A1预计比原定到货时间晚48小时。', case_id='guided')
    run = engine.reply(run['run_id'], run['revision'], text, ['AP-PARTIAL', 'TECH-CURRENT'])
    assert run['status'] == 'awaiting_approval'
    assert run['order']['quantity'] == 600
    assert run['qualification']['eligible_a2'] == 300
    assert len(run['plans']) == 3
    assert not run['approval'] and not run['drafts']

def test_model_misclassified_approval_quantity_is_still_rejected():
    class BadQuantity:
        mode, model_name = 'test_double', 'quantity-confusion'
        def complete_structured(self, **kwargs):
            data = json.loads(kwargs['user_text'])
            return UserInterpretation(kind='evidence', quote=data['text'], quantity=300, explanation='wrong scope')
    engine = FinalsInvestigation()
    run = engine.start('A1延期48小时', case_id='guided')
    engine.model = BadQuantity()
    run = engine.reply(run['run_id'], run['revision'], TEXT, ['AP-PARTIAL', 'TECH-CURRENT'])
    assert run['status'] == 'model_or_validation_error'
    assert run['order']['quantity'] == 600
    assert run['trace'][-1]['candidate_value'] == 300
    assert run['trace'][-1]['source_value'] is None
    assert '误当成' in run['question']
    assert not run['plans'] and not run['drafts']

def test_text_alone_never_grants_approval():
    engine = FinalsInvestigation()
    run = engine.start('A1延期48小时', case_id='guided')
    run = engine.reply(run['run_id'], run['revision'], TEXT, [])
    assert run['status'] == 'awaiting_evidence'
    assert run['qualification']['eligible_a2'] == 0
    assert run['order']['quantity'] == 600 and not run['plans']
