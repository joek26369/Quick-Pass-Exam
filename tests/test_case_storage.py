"""Case drafts persist independently of objective quiz attempts."""
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from study_server import _db, register, _case_progress, _save_case_progress, _progress


def package(tmp_path,name):
    p=tmp_path/name
    (p/'data').mkdir(parents=True);(p/'web').mkdir()
    (p/'manifest.json').write_text(json.dumps({'profile':'ruankao-xitongjicheng'}))
    (p/'web/index.html').write_text('<h1>cases</h1>')
    (p/'data/questions.json').write_text('[]')
    (p/'data/cases.json').write_text(json.dumps([{'id':'case1','sub_questions':[{'id':'c1-q1'},{'id':'c1-q2'}]}]))
    return p


def test_case_only_registration_draft_restart_and_partial_updates(tmp_path):
    lib=tmp_path/'library'; pid,_=register(lib,package(tmp_path,'first'))
    with _db(lib) as conn:
        _save_case_progress(conn,pid,{'sub_question_id':'c1-q1','draft':'我的答案：20 万元。'})
    with _db(lib) as conn:
        result=_save_case_progress(conn,pid,{'sub_question_id':'c1-q1','self_assessment':'partial','review':True,'revealed':True})
        assert result['items']['c1-q1']['draft']=='我的答案：20 万元。'
        assert result['stats']==dict(mastered=0,partial=1,unmastered=0,total=2,assessed=1,drafted=1,review=1)
        assert _progress(conn,pid)['attempt_count']==0
        assert conn.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
    with _db(lib) as conn:
        result=_save_case_progress(conn,pid,{'sub_question_id':'c1-q1','review':False,'self_assessment':'mastered'})
        assert result['stats']['mastered']==1 and result['stats']['review']==0
        assert result['items']['c1-q1']['revealed']


def test_case_ids_are_package_scoped_and_empty_draft_can_be_saved(tmp_path):
    lib=tmp_path/'library'; p1,_=register(lib,package(tmp_path,'first'));p2,_=register(lib,package(tmp_path,'second'))
    with _db(lib) as conn:
        _save_case_progress(conn,p1,{'sub_question_id':'c1-q1','draft':'秘密草稿'})
    with _db(lib) as conn:
        assert _case_progress(conn,p2)['items']=={}
        result=_save_case_progress(conn,p1,{'sub_question_id':'c1-q1','draft':''})
        assert result['items']['c1-q1']['draft']==''


@pytest.mark.parametrize('payload',[
    {'sub_question_id':'unknown','draft':'x'},
    {'sub_question_id':'c1-q1','score':99},
    {'sub_question_id':'c1-q1','review':'false'},
    {'sub_question_id':'c1-q1','self_assessment':'correct'},
    {'sub_question_id':'c1-q1','draft':None},
    {'sub_question_id':'c1-q1','draft':'a'*20001},
    {'sub_question_id':'c1-q1'},
])
def test_invalid_case_updates_do_not_create_records(tmp_path,payload):
    lib=tmp_path/'library';pid,_=register(lib,package(tmp_path,'first'))
    with _db(lib) as conn:
        with pytest.raises(ValueError): _save_case_progress(conn,pid,payload)
        assert _case_progress(conn,pid)['items']=={}


def test_case_http_save_restart_origin_and_invalid_score(tmp_path):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    from study_server import make_handler
    lib=tmp_path/'library';pid,_=register(lib,package(tmp_path,'first'))
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(lib,0))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/api/packages/{pid}/cases/progress'
    def post(body,origin=None):
        headers={'Content-Type':'application/json'}
        if origin: headers['Origin']=origin
        return urlopen(Request(url,data=json.dumps(body).encode(),headers=headers))
    try:
        with post({'sub_question_id':'c1-q1','draft':'跨请求保存','review':True}) as r:
            assert json.load(r)['items']['c1-q1']['review']
        with urlopen(url) as r: assert json.load(r)['items']['c1-q1']['draft']=='跨请求保存'
        with pytest.raises(HTTPError) as exc:
            post({'sub_question_id':'c1-q1','score':4})
        assert exc.value.code==400
        with pytest.raises(HTTPError) as exc:
            post({'sub_question_id':'c1-q1','draft':'恶意覆盖'},'https://example.com')
        assert exc.value.code==403
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
    with _db(lib) as conn:
        assert _case_progress(conn,pid)['items']['c1-q1']['draft']=='跨请求保存'
        assert conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0
