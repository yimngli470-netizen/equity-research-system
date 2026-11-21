"""Public capture and industry-context regressions; no real network or LLM."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select, func

from app.research_evidence.records import *
from app.research_evidence.collect import collect, extract_html, fetch, load_captures
from app.research_evidence.store import import_pack, context_packet
from app.models.accountability import ResearchEvidence, ResearchEvent, ResearchSubmission
from app.models.analysis import AnalysisReport
from tests.conftest import seed_stock

TODAY = date.today()
SOURCE = Source(source_id='issuer', publisher='Example', allowed_hosts=('example.com',), relationship='issuer', freshness_days=90)
RAW = b'<html><body><h1>2026-01-01</h1><p>Revenue increased 20 percent. This is a reported result, not a forecast. Customer utilization is undisclosed.</p></body></html>'


def document(**changes):
    return Document.model_validate(dict(document_id='release', source_id='issuer',title='Results',url='https://example.com/release',tickers=['NVDA'],event_cluster='one-announcement',source_type='financial_release',published_date='2026-01-01',publication_literal='2026-01-01',coverage='full_document',coverage_note='Complete release, not a full filing', **changes))


def fixture_pack(**changes):
    text=extract_html(RAW)
    cap=Capture(document=document(),source=SOURCE,observed_at=datetime.now(timezone.utc)-timedelta(hours=1),fetched_url='https://example.com/release',raw_sha256=hashlib.sha256(RAW).hexdigest(),text_sha256=text_hash(text),text=text,extraction='beautifulsoup-html-text-v1')
    key=capture_id(cap); quote='Revenue increased 20 percent.'; start=text.index(quote)
    p=dict(study_id='test',pack_key='first',revision=1,as_of_date=TODAY,capture_ids=[key],spans=[Span(capture_id=key,start=start,end=start+len(quote),quote=quote,role='supports',claim_type='reported_result',analyst_note='Reported growth, not proof of future economics')],gaps=['Utilization absent'])
    p.update(changes)
    return Pack.model_validate(p), {key:cap}


@pytest.mark.parametrize('url',['http://example.com/a','https://evil.com/a','https://example.com:444/a','https://name:pw@example.com/a'])
def test_source_host_boundary(url):
    with pytest.raises(ValueError): SOURCE.validate_url(url)


def test_redirect_revalidated_before_request():
    seen=[]
    def handler(request):
        seen.append(str(request.url)); return httpx.Response(302,headers={'location':'https://evil.com/a'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ValueError): fetch(c,SOURCE,'https://example.com/a')
    assert seen==['https://example.com/a']


def test_capture_preserves_raw_and_refuses_rerun(tmp_path):
    manifest=Manifest(study_id='test',as_of_date=TODAY,sources=[SOURCE],documents=[document()])
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'text/html'},content=RAW))) as c:
        assert collect(manifest,tmp_path/'capture',client=c)['captured']==1
        caps=load_captures(tmp_path/'capture'); assert len(caps)==1
        with pytest.raises(FileExistsError): collect(manifest,tmp_path/'capture',client=c)
    (tmp_path/'capture/raw/release.html').write_bytes(RAW+b'changed')
    with pytest.raises(ValueError,match='bytes changed'): load_captures(tmp_path/'capture')


def test_failed_http_preserved_once(tmp_path):
    calls=[]
    def handler(r): calls.append(r); return httpx.Response(503)
    manifest=Manifest(study_id='test',as_of_date=TODAY,sources=[SOURCE],documents=[document()])
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out=collect(manifest,tmp_path/'capture',client=c)
    assert out['failed']==1 and len(calls)==1
    assert json.loads((tmp_path/'capture/attempts.jsonl').read_text())['status']=='failed'


def test_exact_span_tamper_and_future_rejected():
    p,c=fixture_pack(); s=p.spans[0]
    with pytest.raises(ValueError,match='exact captured'): validate_pack(p.model_copy(update={'spans':(s.model_copy(update={'quote':'Invented'}),)}),c)
    with pytest.raises(ValueError,match='Future'): validate_pack(p.model_copy(update={'as_of_date':date(2025,1,1)}),c)
    cap=next(iter(c.values()))
    with pytest.raises(ValueError,match='literal absent'):
        Capture.model_validate({**cap.model_dump(),'document':{**cap.document.model_dump(),'publication_literal':'January 1, 2026'}})


def test_duplicate_source_text_and_unknown_preview_explicit():
    p,c=fixture_pack(); cap=next(iter(c.values()))
    twin=cap.model_copy(update={'document':cap.document.model_copy(update={'document_id':'copy','url':'https://example.com/copy'})})
    k=capture_id(twin); c[k]=twin
    packet,_=render_packet(p.model_copy(update={'capture_ids':(*p.capture_ids,k)}),c,'NVDA',today=TODAY)
    assert len(packet['documents'])==1 and len(packet['duplicate_aliases'])==1
    unknown=cap.model_copy(update={'document':cap.document.model_copy(update={'published_date':None,'publication_literal':None,'coverage':'preview'})})
    k=capture_id(unknown)
    packet,_=render_packet(p.model_copy(update={'capture_ids':(k,), 'spans':()}),{k:unknown},'NVDA',today=TODAY)
    assert packet['documents'][0]['freshness']=='unknown' and packet['documents'][0]['coverage']=='preview'


def test_reobservation_reuses_semantics_but_staleness_and_note_change_do_not():
    p,c=fixture_pack(); cap=next(iter(c.values()))
    _,first=render_packet(p,c,'NVDA',today=date(2026,1,10))
    cap2=cap.model_copy(update={'observed_at':cap.observed_at+timedelta(minutes=1)})
    key=capture_id(cap2)
    p2=p.model_copy(update={'pack_key':'second','revision':2,'capture_ids':(key,), 'spans':tuple(s.model_copy(update={'capture_id':key}) for s in p.spans)})
    assert render_packet(p2,{key:cap2},'NVDA',today=date(2026,1,10))[1]==first
    assert render_packet(p,c,'NVDA',today=date(2026,5,1))[1]!=first
    altered=p.model_copy(update={'gaps':('New contrary evidence missing',)})
    assert render_packet(altered,c,'NVDA',today=date(2026,1,10))[1]!=first


@pytest.mark.asyncio
async def test_import_atomic_idempotent_immutable_and_sequential(db):
    p,c=fixture_pack(); row=await import_pack(db,p,c)
    assert (await import_pack(db,p,c)).id==row.id
    with pytest.raises(ValueError,match='immutable'): await import_pack(db,p.model_copy(update={'gaps':('Changed',)}),c)
    with pytest.raises(ValueError,match='sequential'): await import_pack(db,p.model_copy(update={'pack_key':'other','revision':3}),c)
    second=p.model_copy(update={'pack_key':'second','revision':2,'gaps':('Revised coverage',)})
    await import_pack(db,second,c)  # same transaction/created_at, explicit revision wins
    packet,_=await context_packet(db,'NVDA'); assert packet['packets'][0]['pack_key']=='second'
    assert (await context_packet(db,'MU'))[0]['coverage']=='missing'
    for model in (ResearchEvent,ResearchSubmission):
        assert (await db.execute(select(func.count()).select_from(model))).scalar()==0


@pytest.mark.asyncio
async def test_future_observation_blocks(db):
    p,c=fixture_pack(); cap=next(iter(c.values())).model_copy(update={'observed_at':datetime.now(timezone.utc)+timedelta(days=1)})
    k=capture_id(cap); p=p.model_copy(update={'capture_ids':(k,), 'spans':()})
    with pytest.raises(ValueError,match='future capture'): await import_pack(db,p,{k:cap})


def test_assessment_citation_validation():
    p,c=fixture_pack(); packet,_=render_packet(p,c,'NVDA',today=TODAY)
    citation=packet['documents'][0]['spans'][0]['citation']
    result={'external_evidence_assessment':{'claims':[{'claim':'Reported growth','kind':'reported_result','citations':[citation]}]}}
    validate_assessment(result,{'packets':[packet]})
    result['external_evidence_assessment']['claims'][0]['citations']=['made-up']
    with pytest.raises(ValueError,match='not in'): validate_assessment(result,{'packets':[packet]})


@pytest.mark.asyncio
async def test_industry_context_cache_invalidates_and_invalid_answer_not_used(db):
    from app.agents.industry_agent import IndustryAgent
    await seed_stock(db,'NVDA',sector='Technology',industry='Semiconductors')
    agent=object.__new__(IndustryAgent)
    p,c=fixture_pack(); await import_pack(db,p,c); await db.commit()
    context=await agent.build_context(db,'NVDA')
    assert 'Revenue increased 20 percent.' in context and 'Utilization absent' in context
    fp=await agent._full_fingerprint(db,'NVDA')
    report={'summary':'Original','external_evidence_assessment':{'claims':[], 'coverage_gaps':['No claim used']}}
    await agent._save_report(db,'NVDA',report,fp); await db.commit()
    assert await agent._get_cached(db,'NVDA') is not None
    assert await agent._get_smart_cached(db,'NVDA',fp) is not None
    p2=p.model_copy(update={'pack_key':'second','revision':2,'gaps':('Changed external context',)})
    await import_pack(db,p2,c); await db.commit()
    assert await agent._get_cached(db,'NVDA') is None
    assert await agent._get_smart_cached(db,'NVDA',await agent._full_fingerprint(db,'NVDA')) is None
    await agent.build_context(db,'NVDA')
    bad={'summary':'Unsupported', 'external_evidence_assessment':{'claims':[{'claim':'Fake', 'kind':'reported_result','citations':['invented']}]}}
    await agent._save_report(db,'NVDA',bad,await agent._full_fingerprint(db,'NVDA'))
    assert 'error' not in bad and bad['summary']=='Unsupported'
    assert bad['external_evidence_assessment'] is None
    assert bad['external_evidence_status']['status']=='invalid'
    evidence=await db.get(ResearchEvidence,bad['evidence_receipt'])
    assert evidence.payload['response']['summary']=='Unsupported'
    assert 'error' not in evidence.payload['response']
    assert evidence.payload['response']['external_evidence_assessment']['claims'][0]['citations']==['invented']
    await db.commit()
    # Invalid optional evidence must not cause repeated paid/subscription calls.
    assert await agent._get_cached(db,'NVDA') is not None
    assert await agent._get_smart_cached(db,'NVDA',await agent._full_fingerprint(db,'NVDA')) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('assessment', [None, {'claims': [], 'coverage_gaps': []},
    {'claims': [{'claim': 'General inference', 'kind': 'inference', 'citations': []}]}])
async def test_industry_without_pack_keeps_core_and_discards_external_assessment(db, assessment):
    from app.agents.industry_agent import IndustryAgent
    await seed_stock(db,'JNJ',sector='Healthcare',industry='Pharmaceuticals')
    agent=object.__new__(IndustryAgent)
    await agent.build_context(db,'JNJ')
    report={'summary':'Core industry analysis','external_evidence_assessment':assessment}
    fp=await agent._full_fingerprint(db,'JNJ')
    await agent._save_report(db,'JNJ',report,fp)
    await db.commit()
    assert report['summary']=='Core industry analysis' and 'error' not in report
    assert report['external_evidence_assessment'] is None
    assert report['external_evidence_status']=={'status':'not_supplied'}
    evidence=await db.get(ResearchEvidence,report['evidence_receipt'])
    assert evidence.payload['response']['external_evidence_assessment']==assessment
    assert await agent._get_cached(db,'JNJ') is not None
    assert await agent._get_smart_cached(db,'JNJ',fp) is not None


@pytest.mark.asyncio
async def test_industry_failed_context_cannot_reuse_prior_supplied_packet(db):
    from app.agents.industry_agent import IndustryAgent
    await seed_stock(db,'NVDA')
    agent=object.__new__(IndustryAgent)
    await agent.build_context(db,'NVDA')
    assert 'NVDA' in agent._supplied_evidence
    with patch('app.agents.industry_agent.get_computed_metrics',AsyncMock(side_effect=ValueError('context failed'))):
        with pytest.raises(ValueError,match='context failed'):
            await agent.build_context(db,'NVDA')
    assert 'NVDA' not in agent._supplied_evidence
    failure={'error':'context failed'}
    await agent._save_report(db,'NVDA',failure)
    assert 'evidence_receipt' not in failure


def test_date_literal_cannot_launder_wrong_date():
    p,c=fixture_pack(); d=next(iter(c.values())).document.model_dump()
    with pytest.raises(ValueError,match='complete date'):
        Document.model_validate({**d,'publication_literal':'2026'})
    with pytest.raises(ValueError,match='complete date'):
        Document.model_validate({**d,'published_date':'2026-02-01'})


def test_quote_end_cannot_extend_beyond_document():
    p,c=fixture_pack(); key=next(iter(c)); t=c[key].text
    bad=Span(capture_id=key,start=0,end=len(t)+9,quote=t,role='context',claim_type='background',analyst_note='Invalid bounds')
    with pytest.raises(ValueError,match='bounds'):
        validate_pack(p.model_copy(update={'spans':(bad,)}),c)


def test_web_transport_cannot_claim_complete_original_document():
    p,c=fixture_pack(); cap=next(iter(c.values()))
    with pytest.raises(ValueError,match='limited coverage'):
        Capture.model_validate({**cap.model_dump(),'extraction':'web-tool-text-v1'})


def test_manifest_caps_and_https_content_type():
    docs=[document().model_copy(update={'document_id':f'd{i}','url':f'https://example.com/{i}'}) for i in range(25)]
    with pytest.raises(ValueError): Manifest(study_id='test',as_of_date=TODAY,sources=[SOURCE],documents=docs)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'application/pdf'},content=b'pdf'))) as c:
        with pytest.raises(ValueError,match='Only HTML'): fetch(c,SOURCE,'https://example.com/a')
