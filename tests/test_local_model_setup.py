from dataclasses import replace
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from pet.ai import local_candidates
from pet.ai.catalog import Resource
from pet.ai.local_setup import ModelDownload, download_model
from pet.ai.resource_download import DownloadPaused
from pet.config import Settings


def test_missing_saved_paths_reuse_complete_catalog_pair(tmp_path, monkeypatch):
    model = SimpleNamespace(model_path='9b/model.gguf', projector_path='9b/mmproj.gguf',
                            resources=('9b-weights', '9b-projector'), verification='verified')
    monkeypatch.setitem(local_candidates.MODELS, 'qwen3.5-9b', model)
    monkeypatch.setitem(local_candidates.RESOURCES, '9b-weights', SimpleNamespace(bytes=3))
    monkeypatch.setitem(local_candidates.RESOURCES, '9b-projector', SimpleNamespace(bytes=4))
    weights, projector = tmp_path / model.model_path, tmp_path / model.projector_path
    weights.parent.mkdir()
    weights.write_bytes(b'abc')
    projector.write_bytes(b'abcd')
    settings = replace(Settings(), model_path=str(tmp_path / 'old.gguf'), projector_path='')

    candidate = local_candidates.prepared_local_candidates(settings, model_root=tmp_path)[0]
    assert candidate.settings.model_path == str(weights)
    assert candidate.settings.projector_path == str(projector)


def test_incomplete_catalog_files_are_not_selected(tmp_path, monkeypatch):
    monkeypatch.setattr(local_candidates, 'user_model_dir', lambda: tmp_path)
    monkeypatch.setattr(local_candidates, 'LEGACY_MODEL_DIR', tmp_path)
    model = local_candidates.MODELS['qwen3.5-9b']
    weights, projector = tmp_path / model.model_path, tmp_path / model.projector_path
    weights.parent.mkdir()
    weights.write_bytes(b'incomplete')
    projector.touch()
    settings = Settings(model_path=str(weights), projector_path=str(projector))
    assert local_candidates.find_local_model(settings, model_root=tmp_path) is None


def test_download_pauses_resumes_and_only_publishes_verified_bytes(tmp_path):
    payload = b'a' * (1024 * 1024) + b'b' * 256
    ranges = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            byte_range = self.headers.get('Range')
            ranges.append(byte_range)
            offset = int(byte_range[6:-1]) if byte_range else 0
            self.send_response(206 if offset else 200)
            self.send_header('Content-Length', str(len(payload) - offset))
            if offset:
                self.send_header('Content-Range', f'bytes {offset}-{len(payload) - 1}/{len(payload)}')
            self.end_headers()
            self.wfile.write(payload[offset:])

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/model'
            resource = Resource('test', url, 'model.gguf', sha256(payload).hexdigest(), len(payload), 'model')
            plan = ModelDownload('test', 'Test model', tmp_path, (resource,))
            stop = Event()

            def pause_after_first_chunk(phase, done, _total):
                if phase == 'download' and done:
                    stop.set()

            with pytest.raises(DownloadPaused):
                download_model(plan, stop, pause_after_first_chunk)
            partial = tmp_path / 'model.gguf.xuansi.part'
            assert partial.stat().st_size == 1024 * 1024
            assert not (tmp_path / 'model.gguf').exists()
            download_model(plan, Event(), lambda *_: None)
            assert ranges == [None, 'bytes=1048576-']
            assert (tmp_path / 'model.gguf').read_bytes() == payload
            assert not partial.exists()

            invalid = replace(resource, path='bad.gguf', sha256='0' * 64)
            with pytest.raises(ValueError, match='校验失败'):
                download_model(replace(plan, resources=(invalid,)), Event(), lambda *_: None)
            assert not (tmp_path / 'bad.gguf').exists()
        finally:
            server.shutdown()
            thread.join(2)
