<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>차원 균열의 만물상 — 서버 업데이트 도구</title>
<style>
  :root { color-scheme: dark; }
  body {
    font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;
    background: #12141c; color: #e8e8f0;
    display: flex; justify-content: center; padding: 40px 16px;
  }
  .card {
    background: #1c1f2b; border: 1px solid #2e3346; border-radius: 14px;
    padding: 28px 30px; width: 100%; max-width: 480px;
    box-shadow: 0 10px 30px rgba(0,0,0,.4);
  }
  h1 { font-size: 19px; margin: 0 0 4px; }
  p.sub { color: #9aa0b4; font-size: 13px; margin: 0 0 22px; }
  label { display: block; font-size: 13px; color: #b7bccf; margin: 14px 0 6px; }
  input[type=text], input[type=password] {
    width: 100%; box-sizing: border-box; padding: 10px 12px;
    background: #12141c; border: 1px solid #333850; border-radius: 8px;
    color: #fff; font-size: 14px;
  }
  select { width: 100%; box-sizing: border-box; padding: 10px 12px; background: #12141c;
    border: 1px solid #333850; border-radius: 8px; color: #fff; font-size: 14px; }
  .file-row {
    border: 2px dashed #333850; border-radius: 10px; padding: 18px;
    text-align: center; margin-top: 8px; cursor: pointer; transition: .15s;
  }
  .file-row:hover { border-color: #6c8cff; }
  .file-row input { display: none; }
  #fname { font-size: 13px; color: #9aa0b4; margin-top: 6px; word-break: break-all; }
  button {
    width: 100%; margin-top: 22px; padding: 13px; border: none; border-radius: 9px;
    background: linear-gradient(135deg,#6c8cff,#8a6cff); color: #fff; font-size: 15px;
    font-weight: 600; cursor: pointer;
  }
  button:disabled { opacity: .5; cursor: not-allowed; }
  #result {
    margin-top: 18px; padding: 12px 14px; border-radius: 8px; font-size: 13px;
    white-space: pre-wrap; display: none; line-height: 1.5;
  }
  #result.ok  { display: block; background: #12331f; border: 1px solid #2f6b3f; color: #9ef2b0; }
  #result.err { display: block; background: #331414; border: 1px solid #6b2f2f; color: #ffb0b0; }
  .hint { font-size: 12px; color: #6f7590; margin-top: 18px; line-height: 1.6; }
</style>
</head>
<body>
<div class="card">
  <h1>⚡ 서버 무중단 업데이트</h1>
  <p class="sub">서버를 끄지 않고 파일을 업로드해서 바로 반영합니다.</p>

  <label>서버 주소</label>
  <input type="text" id="server" placeholder="http://127.0.0.1:8777" value="http://127.0.0.1:8777">

  <label>관리자 닉네임</label>
  <input type="text" id="admin" placeholder="개발자">

  <label>관리자 비밀번호</label>
  <input type="password" id="pass" placeholder="ADMIN_PASSWORD">

  <label>업로드 대상</label>
  <select id="target">
    <option value="game_logic.py">game_logic.py (게임 규칙/서버 로직)</option>
    <option value="index.html">index.html (게임 화면)</option>
    <option value="__auto">파일 이름 그대로 사용</option>
  </select>

  <label>업로드할 파일</label>
  <div class="file-row" id="dropZone">
    <div>📁 클릭해서 파일 선택</div>
    <div id="fname">선택된 파일 없음</div>
    <input type="file" id="fileInput">
  </div>

  <button id="uploadBtn">업로드 & 즉시 반영</button>

  <div id="result"></div>

  <div class="hint">
    · game_logic.py 는 서버가 문법 검사 후 자동 반영하고, 문제가 있으면 이전 버전으로 자동 롤백합니다.<br>
    · index.html 등 화면/리소스 파일은 업로드 즉시 반영됩니다.<br>
    · server.py 자체는 구조상 재시작이 필요해 이 도구로 반영되지 않습니다.<br>
    · 업로드는 게임 내 최고 관리자(개발자) 권한 계정만 가능합니다.
  </div>
</div>

<script>
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fname = document.getElementById('fname');
const resultBox = document.getElementById('result');
const uploadBtn = document.getElementById('uploadBtn');

dropZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
  fname.textContent = fileInput.files.length ? fileInput.files[0].name : '선택된 파일 없음';
});

uploadBtn.addEventListener('click', async () => {
  const server = document.getElementById('server').value.trim().replace(/\/+$/, '');
  const admin = document.getElementById('admin').value.trim();
  const pass = document.getElementById('pass').value;
  const targetSel = document.getElementById('target').value;
  const file = fileInput.files[0];

  resultBox.className = ''; resultBox.style.display = 'none';

  if (!server || !pass || !file) {
    resultBox.className = 'err';
    resultBox.textContent = '서버 주소, 비밀번호, 파일을 모두 입력/선택해주세요.';
    return;
  }

  const target = targetSel === '__auto' ? file.name : targetSel;

  const fd = new FormData();
  fd.append('pass', pass);
  fd.append('admin', admin);
  fd.append('target', target);
  fd.append('file', file, file.name);

  uploadBtn.disabled = true;
  uploadBtn.textContent = '업로드 중...';

  try {
    const res = await fetch(server + '/admin/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.ok) {
      resultBox.className = 'ok';
      resultBox.textContent = '✅ ' + (data.message || '적용 완료') + '\n대상: ' + data.target;
    } else {
      resultBox.className = 'err';
      resultBox.textContent = '❌ ' + (data.message || data.error || '알 수 없는 오류');
    }
  } catch (e) {
    resultBox.className = 'err';
    resultBox.textContent = '❌ 서버에 연결하지 못했습니다: ' + e.message +
      '\n(서버 주소/포트, 서버 실행 여부, CORS 등을 확인하세요)';
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = '업로드 & 즉시 반영';
  }
});
</script>
</body>
</html>