"""HTTP regression: normal users select folders, not JSON paths."""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import studio_project_discovery as d

spec=importlib.util.spec_from_file_location('studio_local_bridge',ROOT/'tools/studio_local_bridge.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)


def call(url,payload=None,token=None):
    headers={'Content-Type':'application/json'} if payload is not None else {}
    if token:headers['X-CSAI-Token']=token
    req=Request(url,headers=headers,data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urlopen(req,timeout=10) as response:
            return response.status,json.loads(response.read())
    except HTTPError as error:
        return error.code,json.loads(error.read())


def _roots(tmp_path):
    unity=tmp_path/'Unity';(unity/'Assets'/'Demo').mkdir(parents=True);(unity/'ProjectSettings').mkdir()
    ex=unity/'CutSceneAI'/'Exports';ex.mkdir(parents=True)
    csir=ex/'D.csir.json';csir.write_text(json.dumps({'schema_version':'0.1.0','cutscene_id':'case',
        'source':{'engine':'unity'},'name':'Demo','tracks':[{'ced_type':'camera.cut','binding_entity_id':'a','sections':[{'start':0}]}],
        'entities':[{'entity_id':'a','name':'CAM_A','ced_type':'entity.camera'}],'assets':[]}))
    target=tmp_path/'Unreal';(target/'Content'/'Cinematics').mkdir(parents=True)
    (target/'Content'/'Cinematics'/'LSample.umap').write_bytes(b'umap');(target/'Sample.uproject').write_text('{}')
    return unity,target,csir


def test_discover_connect_local_project_folders(tmp_path, monkeypatch):
    u,t,csir=_roots(tmp_path)
    monkeypatch.setattr(d,'browse_project_folder',lambda kind:str(u if kind=='unity' else t))
    web=tmp_path/'web';web.mkdir();(web/'index.html').write_text('test')
    server=ThreadingHTTPServer(('127.0.0.1',0),bridge.create_handler(web,tmp_path/'work'))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        base=f'http://127.0.0.1:{server.server_port}'
        token=call(base+'/api/status')[1]['token']
        assert call(base+'/api/pick-folder',{'kind':'unity'})[0]==403
        status, picked=call(base+'/api/pick-folder',{'kind':'unity'},token)
        assert status==200 and picked['path']==str(u.resolve())
        status,discovered=call(base+'/api/discover',{'unity_folder':str(u),'unreal_folder':str(t)},token)
        assert status==200 and discovered['ready']
        assert len(discovered['unity']['cutscenes'])==1
        status, cfg=call(base+'/api/connect-projects',{'unity_folder':str(u),'unreal_folder':str(t),
            'csir':str(csir.resolve()),'level':'/Game/Cinematics/LSample','source_rights_confirmed':True},token)
        assert status==200 and cfg['source_scope']=='Assets'
        assert cfg['mapping'].startswith(str(tmp_path/'work'))
        assert cfg['source_rights_confirmed'] is True
        status, loaded=call(base+'/api/status')
        assert status==200 and loaded['connection']['cutscene_id']=='case'
    finally:
        server.shutdown();server.server_close();thread.join()


def test_connect_rejects_nonexported_source(tmp_path):
    u,t,_=_roots(tmp_path)
    with __import__('pytest').raises(d.DiscoveryError,match='not a verified export'):
        d.build_connection(str(u),str(t),str(tmp_path/'other.csir.json'),'/Game/Cinematics/LSample',workspace=tmp_path)


def test_api_accepts_assets_folder_and_empty_unreal_map_project(tmp_path):
    u,t,csir=_roots(tmp_path)
    (t/'Content'/'Cinematics'/'LSample.umap').unlink()
    web=tmp_path/'web';web.mkdir();(web/'index.html').write_text('test')
    server=ThreadingHTTPServer(('127.0.0.1',0),bridge.create_handler(web,tmp_path/'work'))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        base=f'http://127.0.0.1:{server.server_port}'
        token=call(base+'/api/status')[1]['token']
        code,options=call(base+'/api/discover',{'unity_folder':str(u/'Assets'),
                                            'unreal_folder':str(t/'Content')},token)
        assert code==200 and options['ready']
        assert options['unreal']['new_level_required']
        assert options['unity']['folder']==str(u.resolve())
        plan_level='/Game/CutSceneAI/AutoTransfer/L_Studio_Fresh'
        assert options['unreal']['levels']==[plan_level]
        code,connected=call(base+'/api/connect-projects',{
            'unity_folder':str(u/'Assets'), 'unreal_folder':str(t/'Content'),
            'csir':str(csir.resolve()),'level':plan_level,'source_rights_confirmed':True},token)
        assert code==200 and connected['auto_create_level'] is True
        assert connected['level_path']==plan_level
        assert not (t/'Content'/'CutSceneAI'/'AutoTransfer'/'L_Studio_Fresh.umap').exists()
    finally:
        server.shutdown();server.server_close();thread.join()


def test_rejected_post_drains_bounded_body_without_dispatch(tmp_path, monkeypatch):
    def forbidden_picker(_):
        raise AssertionError('Unauthorized request reached folder picker')

    monkeypatch.setattr(d, 'browse_project_folder', forbidden_picker)
    web = tmp_path / 'web'
    web.mkdir()
    work = tmp_path / 'work'
    server = ThreadingHTTPServer(('127.0.0.1', 0), bridge.create_handler(web, work))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        token = call(base + '/api/status')[1]['token']
        # Large, deliberately invalid JSON. Authorization must precede parsing.
        for headers in ({}, {'X-CSAI-Token': 'invalid'},
                        {'X-CSAI-Token': token, 'Origin': 'https://foreign.invalid'}):
            conn = HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            try:
                conn.request('POST', '/api/pick-folder', body=b'!' * bridge.MAX_BODY,
                             headers=headers)
                with conn.getresponse() as response:
                    assert response.status == 403
                    assert 'token' in json.loads(response.read())['error'].lower()
            finally:
                conn.close()
        assert not work.exists()
        assert call(base + '/api/status')[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_post_rejects_oversize_and_ambiguous_framing_without_waiting_for_body(tmp_path):
    web = tmp_path / 'web'
    web.mkdir()
    server = ThreadingHTTPServer(('127.0.0.1', 0), bridge.create_handler(web, tmp_path / 'work'))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for headers, expected in (
            ([('Content-Length', str(bridge.MAX_BODY + 1))], 413),
            ([('Content-Length', '1'), ('Content-Length', '2')], 400),
            ([('Transfer-Encoding', 'chunked')], 400),
        ):
            conn = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                conn.putrequest('POST', '/api/pick-folder')
                for name, value in headers:
                    conn.putheader(name, value)
                conn.endheaders()
                with conn.getresponse() as response:
                    assert response.status == expected
                    assert 'error' in json.loads(response.read())
            finally:
                conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
