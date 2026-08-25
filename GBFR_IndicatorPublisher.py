# -*- coding: utf-8 -*-
"""
GBFR Indicator Publisher
========================
一键发布工具：把本机最新的 GBFR_CooldownIndicator 源码打包成 exe，
上传到 GitHub Release，并更新 version.json（自动更新源），推回仓库。

流程（点「发布」后全自动）：
  1. 校验新版本号 > 当前 version.json 版本号
  2. 改主源码 APP_VERSION / APP_TITLE 为发布版本
  3. 复制对应版本的 PyInstaller spec
  4. PyInstaller 构建单文件 exe
  5. 取 GitHub 凭证（git credential fill，复用已登录的 GCM）
  6. 创建 GitHub Release（tag vX.Y）
  7. 上传 exe 资产
  8. 更新本地 version.json（version / download_url / changelog）
  9. 用 GitHub Contents API 把 version.json / README / 源码 推回仓库
    （走 api.github.com，无需梯子，也不依赖本地 git）
 10. 显示 Release 页面与 exe 下载直链

认证：优先用 git credential fill 从 Git Credential Manager 取 PAT；
      取不到则弹输入框让用户粘贴 Personal Access Token。

本界面中「将发布的内容」区域每一项均可直接编辑或点击「浏览」修改；
只有当你手动修改某项后，版本号变化时才会保留你的自定义值，否则自动刷新为预测值。
"""
import sys
import os
import re
import json
import time
import base64
import socket
import http.client
import subprocess
import threading
import urllib.parse
import urllib.request
import urllib.error
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QGroupBox, QFileDialog, QInputDialog, QMessageBox,
    QGridLayout, QSizePolicy, QDialog, QCheckBox, QDialogButtonBox, QFormLayout,
    QProgressBar, QTabWidget,
)
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QFont

REPO = "Dangoooooo613/GBFR_BuffTimerIndicator"
PYTHON = r"C:/Python311/python.exe"
DEFAULT_ROOT = r"E:/zfh/game/GBFR_指示器/GBFR_Indicator"


def find_root():
    """从本文件向上找含 src/gbfr_overlay_qt_v6.py 与 version.json 的目录。
    冻结成 exe 时 __file__ 指向临时解压目录，改用 exe 所在目录作为起点。"""
    if getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(sys.executable))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(6):
        if os.path.isfile(os.path.join(cur, "src", "gbfr_overlay_qt_v6.py")) and \
           os.path.isfile(os.path.join(cur, "version.json")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return DEFAULT_ROOT if os.path.isdir(DEFAULT_ROOT) else here


def ver_key(s):
    try:
        return [int(x) for x in s.split(".")]
    except Exception:
        return [0]


def ver_gt(a, b):
    return ver_key(a) > ver_key(b)


def ver_to_label(ver):
    """把 x.y 版本号转成构建标签数字：2.61 -> 261, 3.0 -> 300。
    规则是 major*100 + minor（minor 补零到 2 位），与历史 V### 命名完全一致。
    旧写法 ver.replace('.','') 在 3.0 时会得到 '30' 而非 '300'，导致 V300 对不上。"""
    m = re.match(r"^(\d+)\.(\d+)$", ver or "")
    if not m:
        return None
    return "%d%02d" % (int(m.group(1)), int(m.group(2)))


def find_git():
    """自动探测 git.exe 路径（GitHub Desktop / 系统 Git / WorkBuddy PortableGit / PATH）。"""
    import glob
    candidates = []
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    # GitHub Desktop 自带 git
    if local:
        candidates += glob.glob(os.path.join(local, "GitHubDesktop", "app-*",
                                             "resources", "app", "git", "cmd", "git.exe"))
    # 系统 Git for Windows
    candidates += [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
    ]
    # WorkBuddy 自带 PortableGit
    wb = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "PortableGit")
    if os.path.isdir(wb):
        candidates += glob.glob(os.path.join(wb, "versions", "*", "cmd", "git.exe"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "git"  # 退回 PATH 查找


def get_token(root):
    """从 Git Credential Manager 取 PAT。取不到返回 None。"""
    try:
        p = subprocess.run(
            [find_git(), "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            capture_output=True, text=True, cwd=root, timeout=60,
        )
        for line in p.stdout.splitlines():
            if line.startswith("password="):
                return line[9:].strip()
    except Exception:
        pass
    return None


def save_token(token):
    """把 token 存进 Windows 凭据管理器（git credential approve），实现"长期免登"。"""
    try:
        payload = "protocol=https\nhost=github.com\nusername=Dangoooooo613\npassword=%s\n\n" % token
        p = subprocess.run(
            [find_git(), "credential", "approve"],
            input=payload,
            capture_output=True, text=True, timeout=60,
        )
        return p.returncode == 0
    except Exception:
        return False


class TokenDialog(QDialog):
    """带"记住此 token"复选框的 token 输入对话框。"""

    def __init__(self, parent, title, prompt):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt))
        self.le = QLineEdit()
        self.le.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.le)
        self.remember = QCheckBox("记住此 token（保存到 Windows 凭据管理器，下次自动登录）")
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def token_text(self):
        return self.le.text().strip()

    @staticmethod
    def get_token(parent, title, prompt):
        dlg = TokenDialog(parent, title, prompt)
        if dlg.exec() == QDialog.Accepted:
            return dlg.token_text(), dlg.remember.isChecked()
        return None, False



def api_call(method, url, token, data=None, is_binary=False, timeout=180,
              max_retries=4, on_retry=None):
    """GitHub REST API 调用，带指数退避重试。

    国内直连 api.github.com 不稳定（尤其大响应，如 Contents API 回显整个文件），
    单次请求失败会触发 IncompleteRead / URLError / 超时。这里默认重试 4 次，
    退避 2/4/8/16s，覆盖绝大多数瞬断。5xx 也重试；4xx（除 404）不重试直接抛。
    """
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, method=method)
            req.add_header("Authorization", "Bearer " + token)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("X-GitHub-Api-Version", "2022-11-28")
            req.add_header("User-Agent", "GBFR-IndicatorPublisher")
            body = None
            if data is not None:
                if is_binary:
                    req.add_header("Content-Type", "application/octet-stream")
                    body = data
                else:
                    req.add_header("Content-Type", "application/json")
                    body = json.dumps(data).encode("utf-8")
            req.data = body
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last_err = e
            # 读出 GitHub 返回的错误体，便于定位 422/其它校验失败的真实原因
            try:
                e.body = e.read().decode("utf-8", "replace")
            except Exception:
                e.body = ""
            if e.body:
                print(f"[GitHub API {e.code}] {e.body}")
            # 5xx 可重试；4xx（含 404）不重试，直接抛
            if e.code >= 500 and attempt < max_retries:
                if on_retry:
                    on_retry(attempt, f"GitHub API {e.code}，{e.reason}，重试中…")
                time.sleep(2 ** attempt)
                continue
            raise
        except (http.client.IncompleteRead, urllib.error.URLError,
                socket.timeout, ConnectionError, TimeoutError,
                ConnectionResetError, BrokenPipeError) as e:
            last_err = e
            if attempt < max_retries:
                if on_retry:
                    on_retry(attempt, f"网络瞬断（{type(e).__name__}），重试中…")
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_err


def get_or_create_release(repo, tag_name, release_name, token, changelog, timeout=120):
    """创建/复用指定 tag 的 Release。
    - 已存在该 tag 的 Release -> 更新 body 复用。
    - 不存在 -> 先清掉可能残留的同名 git tag 引用，再 POST 新建（避免 422）。
    - 若 422 非 tag 冲突（如其它字段校验失败），抛出并附带 GitHub 原始报错便于诊断。"""
    # 1) 复用已有 Release
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag_name}"
    try:
        existing = json.loads(api_call("GET", url, token, timeout=timeout))
        api_call("PATCH",
                 f"https://api.github.com/repos/{repo}/releases/{existing['id']}",
                 token, {"body": changelog or ("V" + tag_name.lstrip('vV') + " 发布")},
                 timeout=timeout)
        return existing
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    # 2) 先清掉可能残留的同名 tag 引用（Release 被删但 tag 没删时会卡 422）
    try:
        api_call("DELETE",
                 f"https://api.github.com/repos/{repo}/git/refs/tags/{tag_name}",
                 token, timeout=timeout)
    except urllib.error.HTTPError:
        pass
    # 3) 新建 Release（GitHub 会在默认分支 HEAD 上创建 tag）
    payload = {
        "tag_name": tag_name,
        "name": release_name,
        "body": changelog or ("V" + tag_name.lstrip('vV') + " 发布"),
        "draft": False, "prerelease": False,
    }
    try:
        return json.loads(api_call("POST",
                         f"https://api.github.com/repos/{repo}/releases",
                         token, payload, timeout=timeout))
    except urllib.error.HTTPError as e:
        if e.code != 422:
            raise
        body = (getattr(e, "body", "") or "")
        tag_conflict = ("already exist" in body.lower()
                        or "reference already exists" in body.lower()
                        or "tag" in body.lower())
        if tag_conflict:
            # 422 多半是 tag 已存在。可能情形：
            # ① 顶部 GET 因 api.github.com 国内不稳定瞬时 404，导致漏判已有 Release；
            # ② 确实存在同名 git tag 引用（无 Release）。
            # 兜底策略：先按 tag 直接取已有 Release 并 PATCH 复用（幂等、安全）；
            # 若确实连 Release 都没有（404），再删一次残留 tag 引用后重试创建。
            try:
                existing = json.loads(api_call(
                    "GET",
                    f"https://api.github.com/repos/{repo}/releases/tags/{tag_name}",
                    token, timeout=timeout))
                api_call("PATCH",
                         f"https://api.github.com/repos/{repo}/releases/{existing['id']}",
                         token,
                         {"body": changelog or ("V" + tag_name.lstrip('vV') + " 发布")},
                         timeout=timeout)
                return existing
            except urllib.error.HTTPError as ge:
                if ge.code == 404:
                    # 确无任何 Release：删残留 tag 引用后重试创建
                    try:
                        api_call("DELETE",
                                 f"https://api.github.com/repos/{repo}/git/refs/tags/{tag_name}",
                                 token, timeout=timeout)
                    except urllib.error.HTTPError:
                        pass
                    return json.loads(api_call("POST",
                                     f"https://api.github.com/repos/{repo}/releases",
                                     token, payload, timeout=timeout))
                raise
        # 非 tag 冲突的 422（如其它字段校验失败），原样抛出（已带 GitHub 报错体）
        raise


def delete_asset_if_exists(repo, release_id, name, token, timeout=120):
    """上传前先删掉同名的旧资产（重发/补传时避免 422）。"""
    url = f"https://api.github.com/repos/{repo}/releases/{release_id}/assets"
    try:
        for a in json.loads(api_call("GET", url, token, timeout=timeout)):
            if a.get("name") == name:
                api_call("DELETE", a["url"], token, timeout=timeout)
                return True
    except Exception:
        pass
    return False


def api_put_file(repo, path, token, local_path, message, timeout=120,
                  max_retries=4, on_retry=None):
    """用 GitHub Contents API 把本地文件推到仓库（无需 git / 梯子）。

    先 GET 现有文件的 sha（存在才需要），再 PUT 新内容到 main 分支。
    这样 version.json / README / 源码的更新走 api.github.com，
    不受 github.com:443 git 协议被墙的影响。

    重试安全：每次尝试前重新取 sha。若上一次 PUT 实际已生效（响应被截断导致
    IncompleteRead），重试时 GET 到新 sha，PUT 带 sha 做幂等更新，不会 422。
    """
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("ascii")
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            sha = None
            try:
                cur = json.loads(api_call(
                    "GET", f"https://api.github.com/repos/{repo}/contents/{path}",
                    token, timeout=timeout, max_retries=max_retries, on_retry=on_retry))
                sha = cur.get("sha")
            except urllib.error.HTTPError:
                sha = None  # 文件不存在（新仓库）也可创建
            payload = {"message": message, "content": content, "branch": "main"}
            if sha:
                payload["sha"] = sha
            api_call("PUT", f"https://api.github.com/repos/{repo}/contents/{path}",
                     token, payload, timeout=timeout,
                     max_retries=max_retries, on_retry=on_retry)
            return  # 成功
        except urllib.error.HTTPError as e:
            last_err = e
            # 409/422（sha 冲突）重试时靠重新 GET sha 自愈；其他 4xx 直接抛
            if e.code in (409, 422) and attempt < max_retries:
                if on_retry:
                    on_retry(attempt, f"Contents API {e.code}，重试中…")
                time.sleep(2 ** attempt)
                continue
            raise
        except (http.client.IncompleteRead, urllib.error.URLError,
                socket.timeout, ConnectionError, TimeoutError,
                ConnectionResetError, BrokenPipeError) as e:
            last_err = e
            if attempt < max_retries:
                if on_retry:
                    on_retry(attempt, f"网络瞬断（{type(e).__name__}），重试中…")
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_err


def upload_asset(upload_base_url, token, filepath, name, total,
                 on_progress, timeout=900, max_retries=4):
    """流式上传 exe 资产，每 1MB 回调一次进度；失败自动重试。"""
    parsed = urllib.parse.urlparse(upload_base_url)
    host = parsed.netloc
    path = parsed.path + "?" + parsed.query + "&name=" + urllib.parse.quote(name)
    last_err = None
    for attempt in range(1, max_retries + 1):
        conn = None
        try:
            on_progress(0, total)  # 复位进度条（重试时）
            conn = http.client.HTTPSConnection(host, timeout=timeout)
            headers = {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/octet-stream",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Length": str(total),
                "User-Agent": "GBFR-Publisher",
            }
            conn.putrequest("POST", path)
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.endheaders()
            sent = 0
            chunk_size = 1024 * 1024
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    conn.send(chunk)
                    sent += len(chunk)
                    on_progress(sent, total)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
            conn.close()
            conn = None
            if resp.status >= 400:
                raise RuntimeError(f"上传失败 HTTP {resp.status}: {body[:500]}")
            return body
        except Exception as e:
            last_err = e
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            if attempt < max_retries:
                # 重试前等 3 秒
                time.sleep(3)
                continue
            raise
    raise last_err


class Worker(QObject):
    log = Signal(str)
    need_token = Signal()
    finished = Signal(bool, str)
    progress = Signal(int, int)  # (sent_bytes, total_bytes)

    def __init__(self, root, new_ver, changelog, token,
                 src_path, readme_path, vjson_path, exe_path,
                 tag_name, release_name, download_url, raw_url,
                 skip_build=False):
        super().__init__()
        self.root = root
        self.new_ver = new_ver
        self.changelog = changelog
        self.token = token
        self.src_path = src_path
        self.readme_path = readme_path
        self.vjson_path = vjson_path
        self.exe_path = exe_path
        self.tag_name = tag_name
        self.release_name = release_name
        self.download_url = download_url
        self.raw_url = raw_url
        self.skip_build = skip_build

    def run(self):
        try:
            self._publish()
        except Exception as e:
            import traceback
            self.log.emit("[错误] " + str(e))
            self.log.emit(traceback.format_exc())
            self.finished.emit(False, str(e))

    def _publish(self):
        root = self.root
        new_ver = self.new_ver
        src = self.src_path
        vjson = self.vjson_path
        exe_path = self.exe_path
        title = os.path.basename(exe_path)[:-4] if exe_path.endswith(".exe") else ("GBFR_CooldownIndicator_V" + (ver_to_label(new_ver) or new_ver.replace(".", "")))

        # 1) 读取当前版本号（不限制大小，允许同版本重发 / 补传 / 回退）
        self.log.emit(f"[1/9] 读取当前版本号 ...")
        with open(vjson, "r", encoding="utf-8") as f:
            old = json.load(f)
        old_ver = old.get("version", "0.0")
        self.log.emit(f"      当前版本 {old_ver} -> 新版本 {new_ver}")

        # 2) 主源码版本号
        self.log.emit("[2/9] 更新主源码版本号 ...")
        with open(src, "r", encoding="utf-8") as f:
            txt = f.read()
        if 'APP_VERSION = (' in txt:
            # 自 V608 起版本号由 exe 文件名动态推导（_BUILD_NO），源码无需回写，
            # 版本号只活在 exe/spec 文件名里（如 GBFR_CooldownIndicator_V613.exe）。
            self.log.emit("      版本号由 exe 文件名动态推导，无需改写源码")
        else:
            # 旧式字面量写法：回写以保证一致（兼容未迁移的旧仓库）。
            txt = re.sub(r'APP_VERSION = "[^"]*"', f'APP_VERSION = "{new_ver}"', txt)
            txt = re.sub(r'APP_TITLE = "[^"]*"', f'APP_TITLE = "{title}"', txt)
            with open(src, "w", encoding="utf-8") as f:
                f.write(txt)
            self.log.emit(f"      已回写 APP_VERSION={new_ver} / APP_TITLE={title}")

        # 3) 复制 spec
        self.log.emit("[3/9] 准备 PyInstaller spec ...")
        specs = [s for s in os.listdir(root)
                 if re.match(r"GBFR_CooldownIndicator_V\d+\.spec$", s)]

        def sv(s):
            m = re.search(r"V(\d+)\.spec$", s)
            return int(m.group(1)) if m else 0

        template = max(specs, key=sv) if specs else None
        new_spec = title + ".spec"
        if template and template != new_spec:
            with open(os.path.join(root, template), "r", encoding="utf-8") as f:
                stxt = f.read()
            # 防御：剔除 WorkBuddy 沙箱专属的 import sitecustomize 污染块
            # （真实 Windows 机器无该模块，保留会导致 python -m PyInstaller 直接报错）
            stxt = re.sub(
                r"import sitecustomize.*?sitecustomize\._orig_shutil_rmtree\)\n",
                "", stxt, flags=re.S)
            stxt = re.sub(r"name='[^']*'", f"name='{title}'", stxt)
            with open(os.path.join(root, new_spec), "w", encoding="utf-8") as f:
                f.write(stxt)
            self.log.emit(f"      由模板 {template} 生成 {new_spec}")
        elif os.path.isfile(os.path.join(root, new_spec)):
            self.log.emit(f"      已存在 spec：{new_spec}")
        else:
            raise RuntimeError("找不到可用的 spec 模板")

        # 4) 构建 exe
        if self.skip_build and os.path.isfile(exe_path):
            self.log.emit("[4/9] 跳过构建（使用已有 exe）...")
            size_mb = os.path.getsize(exe_path) / 1024 / 1024
            self.log.emit(f"      使用已有：{exe_path}  ({size_mb:.1f} MB)")
        else:
            self.log.emit("[4/9] PyInstaller 构建 exe（约 1 分钟）...")
            proc = subprocess.Popen(
                [PYTHON, "-m", "PyInstaller", new_spec, "--noconfirm",
                 "--workpath", "build_pub", "--distpath", "dist"],
                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.log.emit("      " + line)
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"PyInstaller 构建失败，返回码 {proc.returncode}")
            if not os.path.isfile(exe_path):
                raise RuntimeError(f"构建产物不存在：{exe_path}")
            size_mb = os.path.getsize(exe_path) / 1024 / 1024
            self.log.emit(f"      构建完成：{exe_path}  ({size_mb:.1f} MB)")

        # 5) token
        self.log.emit("[5/9] 获取 GitHub 凭证 ...")
        token = self.token or get_token(root)
        if not token:
            self.need_token.emit()
            return
        self.token = token

        # 6) 创建 / 复用 release（已存在则补传，避免 tag 冲突）
        self.log.emit("[6/9] 创建 / 复用 GitHub Release ...")
        rel = get_or_create_release(
            REPO, self.tag_name, self.release_name, token,
            self.changelog or ("V" + new_ver + " 发布"))
        upload_url = rel["upload_url"].split("{")[0]
        html_url = rel["html_url"]
        self.log.emit(f"      Release：{html_url}")

        # 7) 上传 exe（流式 + 进度条 + 自动重试）
        self.log.emit("[7/9] 上传 exe 资产（约 %.1f MB）..." % size_mb)
        delete_asset_if_exists(REPO, rel["id"], title + ".exe", token)
        total = os.path.getsize(exe_path)
        self.progress.emit(0, total)
        upload_asset(upload_url, token, exe_path, title + ".exe", total,
                     on_progress=self.progress.emit, timeout=900, max_retries=4)
        self.progress.emit(total, total)
        self.log.emit("      上传完成")

        # 8) 更新 version.json
        self.log.emit("[8/9] 更新 version.json ...")
        old["version"] = new_ver
        old["download_url"] = self.download_url
        # 三语 changelog：把本次新版本 notes 拼到各语言历史前面（保持三语 dict，绝不写回纯字符串）
        prev = old.get("changelog", {})
        if not isinstance(prev, dict):
            prev = {"zh": prev if isinstance(prev, str) else ""}
        label = "v" + new_ver
        new_zh = "== %s ==\n%s\n\n" % (label, (self.changelog.get("zh", "") or "").strip())
        new_tw = "== %s ==\n%s\n\n" % (label, (self.changelog.get("zh_tw", "") or "").strip())
        new_en = "== %s ==\n%s\n\n" % (label, (self.changelog.get("en", "") or "").strip())
        old["changelog"] = {
            "zh": new_zh + (prev.get("zh", "") or ""),
            "zh_tw": new_tw + (prev.get("zh_tw", "") or prev.get("zh", "") or ""),
            "en": new_en + (prev.get("en", "") or prev.get("zh", "") or ""),
        }
        with open(vjson, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=2)
        self.log.emit("      version.json 已更新（changelog 三语 dict）")

        # 8.5) 把 version.json 也作为 release 资产上传，使 releases/latest/download/version.json
        #      可用（= 更新源走下载 CDN，国内比 raw 快，与 GBFR Logs 显血插件同款机制）
        self.log.emit("[8.5/9] 上传 version.json 资产（更新源走下载 CDN）...")
        delete_asset_if_exists(REPO, rel["id"], "version.json", token)
        vtotal = os.path.getsize(vjson)
        self.progress.emit(0, vtotal)
        upload_asset(upload_url, token, vjson, "version.json", vtotal,
                     on_progress=self.progress.emit, timeout=120, max_retries=3)
        self.progress.emit(vtotal, vtotal)
        self.log.emit("      version.json 资产上传完成")

        # 9) 推回仓库（GitHub Contents API，免去梯子 / git 依赖）
        self.log.emit("[9/9] 推送 version.json / README / 源码 到仓库（API）...")
        push_map = [
            (vjson, "version.json"),
            (self.readme_path, "README.md"),
            (self.src_path, os.path.relpath(self.src_path, root)),
        ]
        for local_p, repo_p in push_map:
            if not os.path.isfile(local_p):
                continue
            api_put_file(REPO, repo_p, token, local_p,
                         f"Release V{new_ver}: update {repo_p}",
                         on_retry=self.log.emit)
            self.log.emit(f"      已推送：{repo_p}")
        self.log.emit("      推送完成（走 GitHub API，无需梯子）")

        self.finished.emit(True, html_url + "|" + self.download_url)


class Publisher(QWidget):
    def __init__(self):
        super().__init__()
        self.root = find_root()
        self.token = None
        self.thread = None
        self.worker = None
        self._manual = {}  # 记录用户手动修改过的字段 key -> True
        self._build_ui()
        self._refresh_paths()

    def _build_ui(self):
        self.setWindowTitle("GBFR Indicator 发布工具  V1.2")
        self.resize(760, 680)
        layout = QVBoxLayout(self)

        # 项目目录
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("项目目录:"))
        self.dir_le = QLineEdit(self.root)
        self.dir_le.textChanged.connect(self._on_root_changed)
        dir_row.addWidget(self.dir_le, 1)
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self._browse_root)
        dir_row.addWidget(btn_browse)
        layout.addLayout(dir_row)

        # 文件清单 —— 全部可编辑、可浏览
        info = QGroupBox("将发布的内容（以下各项均可点击「浏览」或直接编辑修改）")
        grid = QGridLayout(info)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 0)

        self.src_le = self._add_path_row(grid, 0, "源码路径:")
        self.readme_le = self._add_path_row(grid, 1, "README 路径:")
        self.vjson_le = self._add_path_row(grid, 2, "version.json 路径:")
        self.tag_le = self._add_text_row(grid, 3, "将建标签:")
        self.exe_le = self._add_path_row(grid, 4, "将生成 exe:", dir_only=False)
        self.src_url_le = self._add_text_row(grid, 5, "更新源 URL:")
        self.notes_le = self._add_path_row(grid, 6, "更新说明文件:")
        layout.addWidget(info)

        # 版本号 + 说明
        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("新版本号:"))
        self.ver_le = QLineEdit()
        self.ver_le.setPlaceholderText("例如 2.61")
        self.ver_le.textChanged.connect(self._on_ver_changed)
        ver_row.addWidget(self.ver_le, 1)
        self.ver_hint_lbl = QLabel("")
        self.ver_hint_lbl.setStyleSheet("color:#9ca3af;")
        ver_row.addWidget(self.ver_hint_lbl)
        layout.addLayout(ver_row)

        # 跳过构建勾选
        self.skip_build_cb = QCheckBox("跳过构建（已有 exe，直接上传；重发/补传时勾选）")
        layout.addWidget(self.skip_build_cb)

        # 变更日志（三语：来源 release_notes.txt 的 [zh]/[zh_tw]/[en] 三段）
        clog_head = QHBoxLayout()
        clog_head.addWidget(QLabel("更新说明 (changelog, 三语):"))
        clog_head.addStretch(1)
        btn_read_notes = QPushButton("读取说明文件")
        btn_read_notes.clicked.connect(self._load_notes)
        clog_head.addWidget(btn_read_notes)
        layout.addLayout(clog_head)
        self.clog_tabs = QTabWidget()
        self.clog_zh = QPlainTextEdit()
        self.clog_tw = QPlainTextEdit()
        self.clog_en = QPlainTextEdit()
        for w, name in ((self.clog_zh, "中文"), (self.clog_tw, "繁中"), (self.clog_en, "English")):
            w.setMaximumHeight(90)
            w.setPlainText("（将由 release_notes.txt 自动填入）")
            self.clog_tabs.addTab(w, name)
        self._clog_manual = False

        def _mark_manual(*_):
            self._clog_manual = True

        self.clog_zh.textChanged.connect(_mark_manual)
        self.clog_tw.textChanged.connect(_mark_manual)
        self.clog_en.textChanged.connect(_mark_manual)
        layout.addWidget(self.clog_tabs)

        # 上传进度条
        self.progress_label = QLabel("上传进度: 待命")
        self.progress_label.setStyleSheet("color:#9ca3af;")
        layout.addWidget(self.progress_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # 日志
        layout.addWidget(QLabel("发布日志:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log, 1)

        # 按钮
        btn_row = QHBoxLayout()
        self.pub_btn = QPushButton("发布")
        self.pub_btn.clicked.connect(self._publish)
        btn_row.addWidget(self.pub_btn)
        btn_auto = QPushButton("自动探测路径")
        btn_auto.clicked.connect(self._refresh_paths)
        btn_row.addWidget(btn_auto)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _add_path_row(self, grid, row, label, dir_only=False):
        grid.addWidget(QLabel(label), row, 0)
        le = QLineEdit()
        le.setPlaceholderText("路径")
        le.textEdited.connect(lambda: self._manual.__setitem__(self._le_key(le), True))
        grid.addWidget(le, row, 1)
        btn = QPushButton("浏览")
        btn.setMaximumWidth(50)
        if dir_only:
            btn.clicked.connect(lambda: self._browse_dir(le))
        else:
            btn.clicked.connect(lambda: self._browse_file(le))
        grid.addWidget(btn, row, 2)
        return le

    def _add_text_row(self, grid, row, label):
        grid.addWidget(QLabel(label), row, 0)
        le = QLineEdit()
        le.textEdited.connect(lambda: self._manual.__setitem__(self._le_key(le), True))
        grid.addWidget(le, row, 1, 1, 2)
        return le

    def _le_key(self, le):
        # 用内存地址标识控件，避免和同名方法冲突
        return f"le_{id(le)}"

    def _browse_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择项目目录", self.dir_le.text())
        if d:
            self.root = d
            self.dir_le.setText(d)
            self._refresh_paths()

    def _on_root_changed(self, text):
        if os.path.isdir(text):
            self.root = text
            self._refresh_paths()

    def _browse_file(self, le):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", le.text())
        if path:
            self._manual[self._le_key(le)] = True
            le.setText(path)

    def _browse_dir(self, le):
        d = QFileDialog.getExistingDirectory(self, "选择目录", le.text())
        if d:
            self._manual[self._le_key(le)] = True
            le.setText(d)

    def _on_ver_changed(self, text):
        self._refresh_paths()

    def _refresh_paths(self):
        root = self.root
        ver = self.ver_le.text().strip() or "<版本>"
        lbl = ver_to_label(ver)
        title = "GBFR_CooldownIndicator_V" + lbl if lbl else "<版本>"

        # 版本提示
        try:
            with open(os.path.join(root, "version.json"), "r", encoding="utf-8") as f:
                cur = json.load(f).get("version", "?")
        except Exception:
            cur = "?"
        self.ver_hint_lbl.setText(f"当前 version.json 版本 {cur}")

        # 各字段默认值
        defaults = {
            self._le_key(self.src_le): os.path.join(root, "src", "gbfr_overlay_qt_v6.py"),
            self._le_key(self.readme_le): os.path.join(root, "README.md"),
            self._le_key(self.vjson_le): os.path.join(root, "version.json"),
            self._le_key(self.tag_le): "v" + ver,
            self._le_key(self.exe_le): os.path.join(root, "dist", title + ".exe"),
            self._le_key(self.src_url_le): f"https://github.com/{REPO}/releases/latest/download/version.json",
            self._le_key(self.notes_le): os.path.join(root, "release_notes.txt"),
        }

        mapping = {
            self.src_le: defaults[self._le_key(self.src_le)],
            self.readme_le: defaults[self._le_key(self.readme_le)],
            self.vjson_le: defaults[self._le_key(self.vjson_le)],
            self.tag_le: defaults[self._le_key(self.tag_le)],
            self.exe_le: defaults[self._le_key(self.exe_le)],
            self.src_url_le: defaults[self._le_key(self.src_url_le)],
            self.notes_le: defaults[self._le_key(self.notes_le)],
        }

        for le, val in mapping.items():
            key = self._le_key(le)
            if not le.text().strip() or key not in self._manual:
                le.setText(val)

        # 自动从 release_notes.txt 载入更新说明（除非用户手动改过文本框）
        if not self._clog_manual:
            np = self.notes_le.text().strip()
            if os.path.isfile(np):
                try:
                    with open(np, "r", encoding="utf-8") as f:
                        txt = f.read().strip()
                    self._fill_notes(txt)
                except Exception:
                    pass

    def _split_notes(self, text):
        """按 [zh]/[zh_tw]/[en] 把三语 notes 分段；无标记则整体作为 zh。"""
        import re
        parts = {"zh": None, "zh_tw": None, "en": None}
        pat = re.compile(r"^\s*\[(zh|zh_tw|en)\]\s*$", re.M)
        matches = list(pat.finditer(text))
        if not matches:
            return {"zh": text.strip(), "zh_tw": "", "en": ""}
        for i, m in enumerate(matches):
            key = m.group(1)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            parts[key] = text[start:end].strip()
        return parts

    def _fill_notes(self, text):
        """把三语 notes 文本填进三个语言标签页。"""
        p = self._split_notes(text)
        self.clog_zh.blockSignals(True)
        self.clog_tw.blockSignals(True)
        self.clog_en.blockSignals(True)
        self.clog_zh.setPlainText(p.get("zh") or "")
        self.clog_tw.setPlainText(p.get("zh_tw") or "")
        self.clog_en.setPlainText(p.get("en") or "")
        self.clog_zh.blockSignals(False)
        self.clog_tw.blockSignals(False)
        self.clog_en.blockSignals(False)

    def _load_notes(self):
        """从更新说明文件读取三语内容填入标签页。"""
        p = self.notes_le.text().strip()
        if not p:
            return
        if not os.path.isfile(p):
            QMessageBox.warning(self, "说明文件", "找不到文件：%s" % p)
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                txt = f.read().strip()
            self._fill_notes(txt)
            self._clog_manual = False
            self.log.appendPlainText("[说明] 已从 %s 读取更新说明（三语）" % os.path.basename(p))
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))

    def _on_progress(self, sent, total):
        if total > 0:
            self.progress.setValue(int(sent * 100 / total))
        self.progress_label.setText(
            "上传进度: %.1f / %.1f MB (%.0f%%)" % (
                sent / 1048576.0, total / 1048576.0,
                (sent * 100.0 / total) if total else 0))

    def _publish(self):
        self._refresh_paths()
        new_ver = self.ver_le.text().strip()
        if not re.match(r"^\d+\.\d+$", new_ver):
            QMessageBox.warning(self, "版本号", "请输入形如 2.60 的版本号")
            return

        # 检查关键文件是否存在
        for name, path in [("源码", self.src_le.text()),
                           ("version.json", self.vjson_le.text())]:
            if not os.path.isfile(path):
                QMessageBox.warning(self, "路径检查", f"{name} 不存在：{path}")
                return

        self.pub_btn.setEnabled(False)
        self.log.clear()
        self.log.appendPlainText("开始发布流程 ...")
        self.progress.setValue(0)
        self.progress_label.setText("上传进度: 待命")

        # 主线程先取 token（避免在工作线程弹 UI）
        if not self.token:
            self.token = get_token(self.root)
        if not self.token:
            tok, remember = TokenDialog.get_token(
                self, "GitHub Token",
                "未能从本机取到凭证，请粘贴 GitHub Personal Access Token（需 repo 权限）：")
            if not tok:
                self.log.appendPlainText("[取消] 未提供 token")
                self.pub_btn.setEnabled(True)
                return
            self.token = tok
            if remember:
                if save_token(self.token):
                    self.log.appendPlainText("[凭证] 已记住 token 到 Windows 凭据管理器")
                else:
                    self.log.appendPlainText("[凭证] 记住 token 失败（不影响本次发布）")

        title = "GBFR_CooldownIndicator_V" + (ver_to_label(new_ver) or new_ver.replace(".", ""))
        self.worker = Worker(
            self.root, new_ver, {"zh": self.clog_zh.toPlainText().strip(), "zh_tw": self.clog_tw.toPlainText().strip(), "en": self.clog_en.toPlainText().strip()}, self.token,
            src_path=self.src_le.text(),
            readme_path=self.readme_le.text(),
            vjson_path=self.vjson_le.text(),
            exe_path=self.exe_le.text(),
            tag_name=self.tag_le.text().strip() or ("v" + new_ver),
            release_name=f"GBFR Cooldown Indicator V{new_ver}",
            download_url=f"https://github.com/{REPO}/releases/latest/download/{title}.exe",
            raw_url=self.src_url_le.text().strip(),
            skip_build=self.skip_build_cb.isChecked(),
        )
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.need_token.connect(self._on_need_token)
        self.worker.finished.connect(self._on_finished)
        self.worker.progress.connect(self._on_progress)
        self.thread.start()

    def _on_need_token(self):
        tok, remember = TokenDialog.get_token(
            self, "GitHub Token", "发布时需要 GitHub Token，请粘贴：")
        if tok:
            self.token = tok
            if remember:
                if save_token(self.token):
                    self.log.appendPlainText("[凭证] 已记住 token 到 Windows 凭据管理器")
                else:
                    self.log.appendPlainText("[凭证] 记住 token 失败（不影响本次发布）")
            # 重新跑发布（worker 已退出，新建一个）
            self.worker = Worker(
                self.root, self.ver_le.text().strip(),
                {"zh": self.clog_zh.toPlainText().strip(), "zh_tw": self.clog_tw.toPlainText().strip(), "en": self.clog_en.toPlainText().strip()}, self.token,
                src_path=self.src_le.text(),
                readme_path=self.readme_le.text(),
                vjson_path=self.vjson_le.text(),
                exe_path=self.exe_le.text(),
                tag_name=self.tag_le.text().strip() or ("v" + self.ver_le.text().strip()),
                release_name=f"GBFR Cooldown Indicator V{self.ver_le.text().strip()}",
                download_url=f"https://github.com/{REPO}/releases/latest/download/GBFR_CooldownIndicator_V{ver_to_label(self.ver_le.text().strip()) or self.ver_le.text().strip().replace('.', '')}.exe",
                raw_url=self.src_url_le.text().strip(),
                skip_build=self.skip_build_cb.isChecked(),
            )
            self.thread = threading.Thread(target=self.worker.run, daemon=True)
            self.worker.log.connect(self.log.appendPlainText)
            self.worker.need_token.connect(self._on_need_token)
            self.worker.finished.connect(self._on_finished)
            self.worker.progress.connect(self._on_progress)
            self.thread.start()
        else:
            self.log.appendPlainText("[取消] 未提供 token")
            self.pub_btn.setEnabled(True)

    def _on_finished(self, ok, msg):
        self.pub_btn.setEnabled(True)
        if ok:
            html_url, dl = (msg.split("|") + ["", ""])[:2]
            self.log.appendPlainText("")
            self.log.appendPlainText("===== 发布成功 =====")
            self.log.appendPlainText("Release 页面: " + html_url)
            self.log.appendPlainText("下载直链   : " + dl)
            QMessageBox.information(
                self, "完成",
                "发布成功！\n\nRelease: " + html_url + "\n下载: " + dl)
        else:
            self.log.appendPlainText("===== 发布失败 =====")
            self.log.appendPlainText(str(msg))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Publisher()
    w.show()
    sys.exit(app.exec())
