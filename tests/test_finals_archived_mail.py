from delivery_guard.finals_agent import FinalsInvestigation


def test_archived_mail_is_inventory_only_not_current_evidence():
    engine = FinalsInvestigation()
    assert 'MAIL-DELAY' in engine.registry
    run = engine.start('A1延期48小时', case_id='guided')
    run = engine.reply(run['run_id'], run['revision'], '本订单批准使用300个A2，请核对附件', ['AP-PARTIAL'])
    assert run['status'] == 'awaiting_approval'
    assert run['order']['delay_hours'] == 48
    assert 'MAIL-DELAY' not in run['active_documents']
    assert 'MAIL-DELAY' not in run['known_sources']
    assert all(c['citation']['document_id'] != 'MAIL-DELAY' for c in run['wiki']['claims'])
    assert set(run['known_sources']) <= set(run['active_documents'])
