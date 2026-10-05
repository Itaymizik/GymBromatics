import copy
import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient
import uvicorn

from gymbromatics.api import create_app
from gymbromatics.chat import reply
from gymbromatics.feedback_provider import FeedbackError


class Provider:
    model='test-only'
    def __init__(self): self.requests=[];self.bad=False;self.error=False;self.content=None
    def generate(self,system,payload,schema):
        self.requests.append(copy.deepcopy(payload))
        if self.error: raise FeedbackError('quota_exceeded')
        selected=payload['selected_rep'] or 'r1'
        if self.content is not None: return {'content':copy.deepcopy(self.content)}
        return {'content':{'paragraphs':[{'text':'משך העלייה מתועד בנתוני החזרה. ניתן לצפות בחזרה ולבדוק את הסימונים.',
                                         'evidence_ids':['invented' if self.bad else selected+'.ascent_duration']}]}}


@pytest.fixture
def data(): return json.loads(Path('demo_artifacts/squatsample_dashboard.json').read_text(encoding='utf-8'))


def test_history_selection_and_changed_bounds(data):
    provider=Provider()
    first=reply(data,'מה קרה כאן?',data['repetitions'][1]['id'],None,[],None,provider)
    assert provider.requests[-1]['selected_rep']=='r2'
    link=first['paragraphs'][0]['evidence'][0]['links'][0]
    assert link['rep_id']==data['repetitions'][1]['id']
    assert link['frame']==data['repetitions'][1]['bottom']
    second=reply(data,'ומה לגבי הקודמת?',None,None,first['history'],first['revision'],provider)
    assert len(provider.requests[-1]['history'])==2 and not second['history_reset']
    data['repetitions'][1]['end']-=2
    changed=reply(data,'בדוק שוב',None,None,second['history'],second['revision'],provider)
    assert changed['history_reset'] and provider.requests[-1]['history']==[]
    assert 'samples' not in provider.requests[-1]['evidence']


def test_unknown_evidence_not_displayed(data):
    provider=Provider();provider.bad=True
    with pytest.raises(FeedbackError,match='invalid_chat_response'):
        reply(data,'בדיקה',None,None,[],None,provider)
    with pytest.raises(ValueError): reply(data,'בדיקה','wrong',None,[],None,provider)


def test_unknown_evidence_is_filtered_when_another_reference_is_valid(data):
    provider=Provider()
    provider.content={'paragraphs':[{'text':'משך העלייה מופיע בראיות של החזרה.',
        'evidence_ids':['invented','r1.ascent_duration','r1.ascent_duration']}]}
    result=reply(data,'בדיקה',None,None,[],None,provider)
    assert [item['id'] for item in result['paragraphs'][0]['evidence']]==['r1.ascent_duration']


def test_numeric_claim_must_match_cited_evidence(data,caplog):
    provider=Provider()
    provider.content={'paragraphs':[{'text':'משך העלייה הוא 0.87 שניות.',
        'evidence_ids':['r1.ascent_duration']}]}
    result=reply(data,'כמה זמן?',None,None,[],None,provider)
    assert result['paragraphs'][0]['text'].endswith('שניות.')
    provider.content['paragraphs'][0]['text']='משך העלייה הוא 99 שניות.'
    with pytest.raises(FeedbackError,match='invalid_chat_response'):
        reply(data,'כמה זמן?',None,None,[],None,provider)
    assert 'reason=ungrounded_number' in caplog.text


def test_cited_repetition_ordinal_is_grounded(data):
    provider=Provider()
    provider.content={'paragraphs':[{'text':'בחזרה 1 משך העלייה מופיע בראיות.',
        'evidence_ids':['r1.ascent_duration']}]}
    result=reply(data,'איזו חזרה?',None,None,[],None,provider)
    assert result['paragraphs'][0]['evidence'][0]['id']=='r1.ascent_duration'


@pytest.fixture
def api():
    provider=Provider()
    app=create_app([Path('demo_artifacts/squatsample_dashboard.html'),Path('demo_artifacts/squat_test2_dashboard.html')],provider)
    with TestClient(app,base_url='http://testserver') as client:
        yield app,client,provider


def post(app,client,body,token=True,origin=None):
    headers={'Origin':origin or 'http://testserver'}
    if token:headers['X-Chat-Token']=app.state.runtime.page_token
    response=client.post('/sessions/'+body['analysis_id']+'/chat',json=body,headers=headers)
    return response.status_code,response.json()


def test_server_authority_and_limits(api,data):
    app,client,provider=api
    body={'analysis_id':data['analysis_id'],'repetitions':data['repetitions'],'message':'בדיקה'}
    assert post(app,client,body,token=False)[0]==403
    assert post(app,client,body,origin='https://other.example')[0]==403
    assert not provider.requests
    status,result=post(app,client,body)
    assert status==200 and 'history' not in result
    assert result['conversation_id'] in app.state.runtime.conversations
    assert post(app,client,{**body,'message':'x'*1501})==(422,{'error':'invalid_request'})
    assert post(app,client,{**body,'repetitions':[{'id':'bad'}]})==(422,{'error':'invalid_request'})
    provider.error=True
    assert post(app,client,body)[1]['error']=='quota_exceeded'
    for path in ('/.env.local','/../.env.local','/outputs/squatsample_landmarks.json'):
        assert client.get(path).status_code==404


def test_health_and_session_contract(api,data):
    app,client,_=api
    assert client.get('/health/live').json()=={'status':'live'}
    ready=client.get('/health/ready')
    assert ready.status_code==200 and ready.json()['status']=='ready'
    metadata=client.get('/api/sessions/'+data['analysis_id'])
    assert metadata.status_code==200
    assert metadata.json()['analysis_id']==data['analysis_id']
    page=client.get('/sessions/'+data['analysis_id'])
    assert page.status_code==200
    assert app.state.runtime.page_token in page.text


def test_chat_ui_accepts_secure_cloud_origin():
    source=Path('gymbromatics/chat_ui.js').read_text(encoding='utf-8')
    assert "['http:','https:'].includes(location.protocol)" in source
    for name in ('squatsample','squat_test2'):
        artifact=Path(f'demo_artifacts/{name}_dashboard.html').read_text(encoding='utf-8')
        assert "['http:','https:'].includes(location.protocol)" in artifact


@pytest.fixture
def live_server():
    provider=Provider()
    app=create_app([Path('demo_artifacts/squatsample_dashboard.html'),Path('demo_artifacts/squat_test2_dashboard.html')],provider)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    service=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=service.run,daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not service.started and time.monotonic()<deadline: time.sleep(.02)
    if not service.started: pytest.fail('Uvicorn did not start')
    yield app,f'http://127.0.0.1:{port}',provider
    service.should_exit=True;thread.join(timeout=5)


@pytest.mark.skipif(os.environ.get('RUN_DASHBOARD_BROWSER_TEST')!='1',reason='Opt-in Chromium')
def test_chat_browser(live_server):
    from playwright.sync_api import sync_playwright
    app,url,provider=live_server
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chromium')
        for i,(identity,record) in enumerate(app.state.runtime.sessions.items()):
            page=browser.new_page(viewport={'width':1280,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'{url}/sessions/{identity}')
            rep=record['data']['repetitions'][1]
            page.locator('#chat-rep').select_option(rep['id'])
            page.locator('#chat-input').fill('מה אפשר ללמוד מהחזרה הזו?')
            page.locator('#chat-send').click()
            page.locator('.chat-message.assistant').wait_for()
            assert provider.requests[-1]['selected_rep']=='r2'
            page.locator('.chat-evidence button').first.click()
            assert page.locator('#chat-rep').input_value()==rep['id']
            assert page.locator('#video').evaluate('v=>v.currentTime')==pytest.approx(rep['bottom']/record['data']['fps'],abs=.1)
            page.locator('#chat-input').fill('תסביר עוד')
            page.locator('#chat-send').click()
            page.wait_for_function("document.querySelectorAll('.chat-message.assistant').length===2")
            assert len(provider.requests[-1]['history'])==2
            page.locator('#mark-end').evaluate("e=>{e.dispatchEvent(new Event('pointerdown'));e.value=Number(e.value)-1;e.dispatchEvent(new Event('input'));e.dispatchEvent(new Event('change'));}")
            assert page.locator('.chat-evidence button').first.is_disabled()
            page.locator('#chat-input').fill('בדוק לפי הסימונים החדשים')
            page.locator('#chat-send').click()
            page.wait_for_function("document.querySelectorAll('.chat-message.assistant').length===3")
            assert provider.requests[-1]['history']==[]
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('.chat-panel').screenshot(path=f'outputs/chat_preview_{i+1}.png')
            assert not errors
            page.close()
        page=browser.new_page()
        page.goto(Path('demo_artifacts/squatsample_dashboard.html').resolve().as_uri())
        assert page.locator('#chat-send').is_disabled()
        browser.close()
