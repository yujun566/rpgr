# -*- coding: utf-8 -*-
"""
🌐 차원 균열의 만물상 — 온라인 서버 (뼈대)
표준 라이브러리만 사용 (설치 불필요)

실행: python server.py
기본 포트: 8777

이 파일은 "소켓을 열고 요청을 받는 뼈대"만 담당합니다.
실제 게임 규칙(채팅/랭킹/길드/거래소 등)은 game_logic.py 에 있고,
그 파일은 서버를 끄지 않고도(=소켓을 유지한 채) 통째로 교체 + 자동 반영됩니다.

무중단 업데이트 방법:
  1) uploader.html 을 브라우저로 열어서 새 game_logic.py 또는 index.html 등을
     업로드 → 서버가 문법 검사 후 자동으로 반영 (재시작 없음)
  2) 또는 이 파일들을 같은 폴더에 직접 덮어써도, 몇 초 안에 자동 감지되어 반영됨
     (정적 파일은 즉시, game_logic.py 는 자동 감지 스레드가 반영)

주의: server.py 자기 자신(이 파일)을 바꾸는 것은 여전히 재시작이 필요합니다.
      (소켓을 새로 열고 닫는 구조 자체를 바꾸는 것이라 핫스왑 대상이 아님)
"""
import importlib
import json
import os
import py_compile
import shutil
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from socketserver import ThreadingMixIn

import game_logic  # ⚠️ 항상 game_logic.xxx 형태로 참조할 것 (reload 시 즉시 반영되게 하기 위함)

# 한국어 Windows(cp949) 콘솔에서 이모지 출력 시 크래시 방지
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
except Exception:
    pass


def _p(*args):
    try:
        print(*args)
    except Exception:
        try:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            sys.stdout.write(' '.join(str(a) for a in args).encode(enc, 'ignore').decode(enc, 'ignore') + '\n')
        except Exception:
            pass


PORT = int(os.environ.get('RIFT_PORT', 8777))
HOST = os.environ.get('RIFT_HOST', '0.0.0.0')

_reload_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 🔄 game_logic.py 핫 리로드 관련
# ---------------------------------------------------------------------------
GAME_LOGIC_PATH = os.path.abspath(game_logic.__file__.rstrip('c'))  # .pyc 대비
_watch_mtime = [0.0]
try:
    _watch_mtime[0] = os.path.getmtime(GAME_LOGIC_PATH)
except Exception:
    pass


def _do_reload_game_logic():
    """이미 디스크에 있는 game_logic.py 를 다시 읽어 반영."""
    with _reload_lock, game_logic._lock:
        importlib.reload(game_logic)


def apply_game_logic_bytes(content_bytes):
    """업로드된 새 game_logic.py 내용을 검증 후 안전하게 적용.
    문법 오류가 있거나 reload 도중 에러가 나면 이전 버전으로 자동 롤백한다.
    반환: (성공여부, 메시지)
    """
    tmp_path = GAME_LOGIC_PATH + '.new'
    backup_path = GAME_LOGIC_PATH + '.bak'
    with open(tmp_path, 'wb') as f:
        f.write(content_bytes)

    # 1) 문법 검사 (여기서 실패하면 서버는 전혀 영향 없음)
    try:
        py_compile.compile(tmp_path, doraise=True)
    except py_compile.PyCompileError as e:
        os.remove(tmp_path)
        return False, f'문법 오류로 적용 취소됨: {e}'

    # 2) 백업 후 교체 + 리로드
    try:
        if os.path.exists(GAME_LOGIC_PATH):
            shutil.copyfile(GAME_LOGIC_PATH, backup_path)
        os.replace(tmp_path, GAME_LOGIC_PATH)
        _do_reload_game_logic()
        _watch_mtime[0] = os.path.getmtime(GAME_LOGIC_PATH)
        return True, '적용 완료 (서버 재시작 없이 반영됨)'
    except Exception as e:
        # 3) 롤백
        try:
            if os.path.exists(backup_path):
                os.replace(backup_path, GAME_LOGIC_PATH)
                _do_reload_game_logic()
                _watch_mtime[0] = os.path.getmtime(GAME_LOGIC_PATH)
        except Exception:
            pass
        return False, f'적용 실패, 이전 버전으로 롤백함: {e}'


def _auto_watch_loop():
    """게임 로직 파일이 외부에서(FTP, git pull, 직접 덮어쓰기 등) 바뀌면
    업로더를 거치지 않아도 몇 초 안에 자동으로 반영."""
    while True:
        time.sleep(2)
        try:
            mtime = os.path.getmtime(GAME_LOGIC_PATH)
            if mtime != _watch_mtime[0]:
                _watch_mtime[0] = mtime
                _do_reload_game_logic()
                _p('[AUTO-RELOAD] game_logic.py 변경 감지 → 자동 반영 완료')
        except Exception as e:
            _p('[AUTO-RELOAD] 실패:', e)


# ---------------------------------------------------------------------------
# 📦 아주 작은 multipart/form-data 파서 (표준 라이브러리만 사용)
# ---------------------------------------------------------------------------
def parse_multipart(content_type, body):
    fields, files = {}, {}
    if not content_type or 'boundary=' not in content_type:
        return fields, files
    boundary = content_type.split('boundary=')[-1].strip().strip('"')
    boundary_bytes = ('--' + boundary).encode('utf-8')
    for part in body.split(boundary_bytes):
        part = part.strip(b'\r\n')
        if not part or part == b'--':
            continue
        if b'\r\n\r\n' not in part:
            continue
        header_blob, content = part.split(b'\r\n\r\n', 1)
        content = content[:-2] if content.endswith(b'\r\n') else content
        name, filename = None, None
        for line in header_blob.decode('utf-8', 'ignore').split('\r\n'):
            if line.lower().startswith('content-disposition'):
                for seg in line.split(';'):
                    seg = seg.strip()
                    if seg.startswith('name='):
                        name = seg.split('=', 1)[1].strip('"')
                    elif seg.startswith('filename='):
                        filename = seg.split('=', 1)[1].strip('"')
        if name is None:
            continue
        if filename is not None:
            files[name] = {'filename': filename, 'content': content}
        else:
            fields[name] = content.decode('utf-8', 'ignore')
    return fields, files


# 정적 리소스로 업로드 허용할 확장자 (그 외는 game_logic.py 만 특별 취급)
STATIC_UPLOAD_EXTS = {'.html', '.htm', '.js', '.css', '.json', '.xml',
                      '.txt', '.ico', '.png', '.jpg', '.jpeg', '.webmanifest'}


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        try:
            data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass   # 클라이언트가 먼저 연결을 끊음 (탭 전환 등) — 무시

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.end_headers()

    def _serve_static(self, url_path):
        rel = url_path.split('?')[0]
        if rel in ('', '/'):
            rel = '/index.html'
        safe_rel = os.path.normpath(rel).replace('\\', '/').lstrip('/')
        if safe_rel.startswith('..'):
            return self._send({'ok': False, 'error': 'forbidden'}, 403)
        fpath = os.path.join(game_logic.STATIC_DIR, safe_rel)
        if not os.path.abspath(fpath).startswith(os.path.abspath(game_logic.STATIC_DIR)):
            return self._send({'ok': False, 'error': 'forbidden'}, 403)
        if not os.path.isfile(fpath):
            if safe_rel == 'index.html':
                cands = ['index_fixed.html', 'index(1).html', 'index (1).html',
                         'index.htm', 'game.html', 'main.html']
                found = None
                for cand in cands:
                    p2 = os.path.join(game_logic.STATIC_DIR, cand)
                    if os.path.isfile(p2):
                        found = p2; break
                if not found:
                    try:
                        for fn in sorted(os.listdir(game_logic.STATIC_DIR)):
                            if fn.lower().endswith('.html'):
                                found = os.path.join(game_logic.STATIC_DIR, fn); break
                    except Exception:
                        pass
                if found:
                    fpath = found
                else:
                    return self._send({'ok': False, 'error': 'not_found',
                                        'hint': 'server.py 와 같은 폴더에 index.html 을 두세요.'}, 404)
            else:
                return self._send({'ok': False, 'error': 'not_found',
                                    'hint': 'server.py 와 같은 폴더에 index.html 을 두세요.'}, 404)
        ext = os.path.splitext(fpath)[1].lower()
        mime = game_logic._MIME.get(ext, 'application/octet-stream')
        ent = game_logic.get_static_cached(fpath)
        if not ent:
            return self._send({'ok': False, 'error': 'read_failed'}, 500)
        data = ent['raw']
        if ext == '.html' and b'rel="canonical"' not in data and b"rel='canonical'" not in data:
            try:
                if b'<head>' in data:
                    data = data.replace(b'<head>', b'<head>\n    ' + game_logic.CANONICAL_TAG, 1)
                elif b'<meta charset' in data:
                    idx = data.find(b'<meta charset')
                    end = data.find(b'>', idx)
                    if end != -1:
                        data = data[:end+1] + b'\n    ' + game_logic.CANONICAL_TAG + data[end+1:]
            except Exception:
                pass
        use_gz = False
        if ent['gz'] and data is ent['raw']:
            ae = (self.headers.get('Accept-Encoding') or '')
            if 'gzip' in ae:
                data = ent['gz']; use_gz = True
        elif ext == '.html':
            ae = (self.headers.get('Accept-Encoding') or '')
            if 'gzip' in ae:
                try:
                    data = game_logic._gzip.compress(data, 6); use_gz = True
                except Exception:
                    pass
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Access-Control-Allow-Origin', '*')
        if use_gz:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if not game_logic.rate_ok(self.client_address[0], u.path):
            return self._send({'ok': False, 'error': 'rate_limited'}, 429)
        if u.path == '/chat/poll':
            q = parse_qs(u.query)
            room = (q.get('room') or ['global'])[0][:40]
            since = int((q.get('since') or [0])[0] or 0)
            wait = int((q.get('wait') or [15])[0] or 15)
            try:
                return self._send(game_logic.chat_poll(room, since, wait))
            except Exception as e:
                return self._send({'ok': False, 'error': str(e)}, 500)
        if u.path == '/sw.js':
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(game_logic.SW_JS)))
            self.end_headers()
            self.wfile.write(game_logic.SW_JS)
            return
        if u.path not in game_logic.API_PATHS:
            return self._serve_static(u.path)
        try:
            self._send(game_logic.api(u.path, parse_qs(u.query), {}))
        except Exception as e:
            self._send({'ok': False, 'error': str(e)}, 500)

    # ------------------------------------------------------------------
    # 🚀 무중단 업데이트: 파일 업로드
    # ------------------------------------------------------------------
    def _handle_upload(self, content_type, raw_body):
        fields, files = parse_multipart(content_type, raw_body)
        if str(fields.get('pass', '')) != game_logic.ADMIN_PASSWORD:
            return self._send({'ok': False, 'error': 'auth_failed'}, 403)
        admin_nick = str(fields.get('admin', ''))[:20].strip()
        with game_logic.db_ctx() as c:
            rank = game_logic.rank_of(c, admin_nick)
        if rank < 7:
            return self._send({'ok': False, 'error': 'rank_denied',
                                'need': game_logic.RANK_NAMES[7]}, 403)
        f = files.get('file')
        if not f:
            return self._send({'ok': False, 'error': 'no_file'}, 400)
        target = os.path.basename(str(fields.get('target') or f['filename'] or '').strip())
        if not target or '..' in target:
            return self._send({'ok': False, 'error': 'bad_target'}, 400)

        if target == 'game_logic.py':
            ok, msg = apply_game_logic_bytes(f['content'])
            return self._send({'ok': ok, 'message': msg, 'target': target})

        if target in ('server.py',):
            return self._send({'ok': False, 'error': 'needs_restart',
                                'message': 'server.py 자체 변경은 구조상 서버 재시작이 필요합니다. '
                                           '게임 규칙/데이터는 game_logic.py, 화면/리소스는 정적 파일로 올려주세요.'}, 400)

        ext = os.path.splitext(target)[1].lower()
        if ext not in STATIC_UPLOAD_EXTS:
            return self._send({'ok': False, 'error': 'ext_not_allowed'}, 400)

        dest = os.path.join(game_logic.STATIC_DIR, target)
        try:
            with open(dest, 'wb') as out:
                out.write(f['content'])
        except Exception as e:
            return self._send({'ok': False, 'error': f'write_failed: {e}'}, 500)
        # 정적 캐시는 mtime 기반이라 다음 요청부터 자동으로 새 내용이 나감 (재시작 불필요)
        return self._send({'ok': True, 'message': '적용 완료 (서버 재시작 없이 반영됨)', 'target': target})

    def do_POST(self):
        u = urlparse(self.path)
        if not game_logic.rate_ok(self.client_address[0], u.path):
            return self._send({'ok': False, 'error': 'rate_limited'}, 429)
        content_type = self.headers.get('Content-Type') or ''
        try:
            n = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(n) if n else b''
        except Exception:
            raw = b''

        if u.path == '/admin/upload':
            return self._handle_upload(content_type, raw)

        try:
            body = json.loads(raw or b'{}')
        except Exception:
            body = {}
        if u.path == '/chat/poll':
            try:
                room = str(body.get('room') or 'global')[:40]
                since = int(body.get('since') or 0)
                wait = int(body.get('wait') or 15)
                return self._send(game_logic.chat_poll(room, since, wait))
            except Exception as e:
                return self._send({'ok': False, 'error': str(e)}, 500)
        try:
            self._send(game_logic.api(u.path, parse_qs(u.query), body))
        except Exception as e:
            self._send({'ok': False, 'error': str(e)}, 500)

    def log_message(self, *a):
        pass  # 콘솔 조용히


class ThreadedHTTP(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True   # 재시작 시 'Address in use' (TIME_WAIT) 방지


def start_background():
    """게임 런처에서 서버를 백그라운드로 띄울 때 사용"""
    game_logic.init_db()
    srv = ThreadedHTTP((HOST, PORT), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    threading.Thread(target=_auto_watch_loop, daemon=True).start()
    return srv


if __name__ == '__main__':
    game_logic.init_db()
    _p('=' * 52)
    _p('[SERVER] 차원 균열의 만물상 - 온라인 서버')
    _p(f'   바인딩 : {HOST}:{PORT}')
    _p(f'   DB     : {game_logic.DB_PATH}')
    _p(f'   정적파일: {game_logic.STATIC_DIR} (index.html 을 여기 두세요)')
    _p(f'   속도제한: IP당 10초 {game_logic.RATE_LIMIT}회')
    _p('   무중단 업데이트: uploader.html 로 game_logic.py / index.html 등 업로드 가능')
    try:
        import socket as _sk
        s = _sk.socket(_sk.AF_INET, _sk.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        _p(f'   내부 IP : http://{s.getsockname()[0]}:{PORT}')
        s.close()
    except Exception:
        pass
    _p('   같은 PC : http://127.0.0.1:%d  (브라우저로 열면 게임이 바로 실행됩니다)' % PORT)
    _p('=' * 52)
    _p('종료하려면 Ctrl+C')
    threading.Thread(target=_auto_watch_loop, daemon=True).start()
    while True:
        try:
            ThreadedHTTP((HOST, PORT), Handler).serve_forever()
        except KeyboardInterrupt:
            _p('\n서버를 종료합니다.')
            break
        except OSError as e:
            if getattr(e, 'errno', None) == 98:
                _p('')
                _p('[오류] 포트 %d 를 이미 다른 프로세스가 사용 중입니다!' % PORT)
                _p('  이전에 켜둔 서버가 아직 실행 중일 가능성이 큽니다.')
                _p('  아래 명령으로 종료 후 다시 실행하세요:')
                _p('    fuser -k %d/tcp' % PORT)
                _p('  또는:')
                _p('    pkill -f server.py')
            else:
                raise
            break
        except Exception as e:
            _p('[서버 오류] %r — 3초 후 자동 재시작' % (e,))
            time.sleep(3)