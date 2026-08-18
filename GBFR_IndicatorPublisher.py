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
  9. git add + commit + push 回仓库（用 insteadOf 注入 token，避免 GCM 卡死）
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
import subprocess
import threading
import urllib.parse
import urllib.request
import urllib.error
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QGroupBox, QFileDialog, QInputDialog, QMessageBox,
    QGridLayout, QSizePolicy, QDialog, QCheckBox, QDialogButtonBox, QFormLayout,
)
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QFont

REPO = "Dangoooooo613/GBFR_BuffTimerIndicator"
PYTHON = r"C:/Python311/python.exe"
DEFAULT_ROOT = r"E:/zfh/game/GBFR_指示器/GBFR_Indicator"


def find_root():
    """从本文件向上找含 src/gbfr_overlay_qt_v6.py 与 version.json 的目录。"""
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



def api_call(method, url, token, data=None, is_binary=False, timeout=180):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
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


class Worker(QObject):
    log = Signal(str)
    need_token = Signal()
    finished = Signal(bool, str)

    def __init__(self, root, new_ver, changelog, token,
                 src_path, readme_path, vjson_path, exe_path,
                 tag_name, release_name, download_url, raw_url):
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
        title = os.path.basename(exe_path)[:-4] if exe_path.endswith(".exe") else ("GBFR_CooldownIndicator_V" + new_ver.replace(".", ""))

        # 1) 校验版本号
        self.log.emit(f"[1/9] 校验版本号 {new_ver} ...")
        with open(vjson, "r", encoding="utf-8") as f:
            old = json.load(f)
        old_ver = old.get("version", "0.0")
        if not ver_gt(new_ver, old_ver):
            raise RuntimeError(f"新版本号 {new_ver} 必须大于当前 {old_ver}")
        self.log.emit(f"      当前版本 {old_ver} -> 新版本 {new_ver}  OK")

        # 2) 改主源码版本号
        self.log.emit("[2/9] 更新主源码版本号 ...")
        with open(src, "r", encoding="utf-8") as f:
            txt = f.read()
        txt = re.sub(r'APP_VERSION = "[^"]*"', f'APP_VERSION = "{new_ver}"', txt)
        txt = re.sub(r'APP_TITLE = "[^"]*"', f'APP_TITLE = "{title}"', txt)
        with open(src, "w", encoding="utf-8") as f:
            f.write(txt)
        self.log.emit(f"      已写入 APP_VERSION={new_ver} / APP_TITLE={title}")

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
            stxt = re.sub(r"name='[^']*'", f"name='{title}'", stxt)
            with open(os.path.join(root, new_spec), "w", encoding="utf-8") as f:
                f.write(stxt)
            self.log.emit(f"      由模板 {template} 生成 {new_spec}")
        elif os.path.isfile(os.path.join(root, new_spec)):
            self.log.emit(f"      已存在 spec：{new_spec}")
        else:
            raise RuntimeError("找不到可用的 spec 模板")

        # 4) 构建 exe
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

        # 6) 创建 release
        self.log.emit("[6/9] 创建 GitHub Release ...")
        payload = {
            "tag_name": self.tag_name,
            "name": self.release_name,
            "body": self.changelog or ("V" + new_ver + " 发布"),
            "draft": False, "prerelease": False,
        }
        resp = api_call("POST",
                        f"https://api.github.com/repos/{REPO}/releases",
                        token, payload)
        j = json.loads(resp)
        upload_url = j["upload_url"].split("{")[0]
        html_url = j["html_url"]
        self.log.emit(f"      Release 已创建：{html_url}")

        # 7) 上传 exe
        self.log.emit("[7/9] 上传 exe 资产（约 50MB）...")
        with open(exe_path, "rb") as f:
            data = f.read()
        api_call("POST", upload_url + "?name=" + title + ".exe",
                 token, data, is_binary=True, timeout=300)
        self.log.emit("      上传完成")

        # 8) 更新 version.json
        self.log.emit("[8/9] 更新 version.json ...")
        old["version"] = new_ver
        old["download_url"] = self.download_url
        old["changelog"] = self.changelog or ("V" + new_ver + " 发布")
        with open(vjson, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=2)
        self.log.emit("      version.json 已更新")

        # 9) 推回仓库
        self.log.emit("[9/9] git 提交并推送 ...")
        qtok = urllib.parse.quote(token, safe="")
        instead = f"url.https://{qtok}@github.com/.insteadOf=https://github.com/"
        # 推哪些文件：用户界面中列出的可发布文件（若存在）
        files = []
        for p in [self.vjson_path, self.src_path, self.readme_path,
                  os.path.join(root, new_spec),
                  os.path.join(root, "GBFR_IndicatorPublisher.py")]:
            if os.path.isfile(p):
                files.append(p)
        # 去重并保持相对路径
        seen = set()
        final_files = []
        for p in files:
            rel = os.path.relpath(p, root)
            if rel not in seen:
                seen.add(rel)
                final_files.append(rel)
        g = find_git()
        subprocess.run([g, "add"] + final_files, cwd=root, check=True)
        subprocess.run([g, "commit", "-m",
                        f"Release V{new_ver} (publisher)"],
                       cwd=root, check=True)
        subprocess.run([g, "-c", instead, "push", "origin", "main"],
                       cwd=root, check=True)
        self.log.emit("      推送完成")

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
        self.setWindowTitle("GBFR Indicator 发布工具")
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
        layout.addWidget(info)

        # 版本号 + 说明
        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("新版本号:"))
        self.ver_le = QLineEdit()
        self.ver_le.setPlaceholderText("例如 2.60")
        self.ver_le.textChanged.connect(self._on_ver_changed)
        ver_row.addWidget(self.ver_le, 1)
        self.ver_hint_lbl = QLabel("")
        self.ver_hint_lbl.setStyleSheet("color:#9ca3af;")
        ver_row.addWidget(self.ver_hint_lbl)
        layout.addLayout(ver_row)

        # 变更日志
        layout.addWidget(QLabel("更新说明 (changelog):"))
        self.clog = QPlainTextEdit()
        self.clog.setPlainText("V260：版本号递增（功能与 V250 一致）。")
        self.clog.setMaximumHeight(70)
        layout.addWidget(self.clog)

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

        # 底部提示
        hint = QLabel(
            "提示：V260 目前还不存在。在上面的「新版本号」里填 2.60，点「发布」后，\n"
            "工具会自动改源码版本号、构建 exe、创建 Release v2.60、上传并推送。"
        )
        hint.setStyleSheet("color:#facc15;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

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
        title = "GBFR_CooldownIndicator_V" + ver.replace(".", "") if re.match(r"^\d+\.\d+$", ver) else "<版本>"

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
            self._le_key(self.src_url_le): f"https://raw.githubusercontent.com/{REPO}/main/version.json",
        }

        mapping = {
            self.src_le: defaults[self._le_key(self.src_le)],
            self.readme_le: defaults[self._le_key(self.readme_le)],
            self.vjson_le: defaults[self._le_key(self.vjson_le)],
            self.tag_le: defaults[self._le_key(self.tag_le)],
            self.exe_le: defaults[self._le_key(self.exe_le)],
            self.src_url_le: defaults[self._le_key(self.src_url_le)],
        }

        for le, val in mapping.items():
            key = self._le_key(le)
            if not le.text().strip() or key not in self._manual:
                le.setText(val)

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

        title = "GBFR_CooldownIndicator_V" + new_ver.replace(".", "")
        self.worker = Worker(
            self.root, new_ver, self.clog.toPlainText().strip(), self.token,
            src_path=self.src_le.text(),
            readme_path=self.readme_le.text(),
            vjson_path=self.vjson_le.text(),
            exe_path=self.exe_le.text(),
            tag_name=self.tag_le.text().strip() or ("v" + new_ver),
            release_name=f"GBFR Cooldown Indicator V{new_ver}",
            download_url=f"https://github.com/{REPO}/releases/download/v{new_ver}/{title}.exe",
            raw_url=self.src_url_le.text().strip(),
        )
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.need_token.connect(self._on_need_token)
        self.worker.finished.connect(self._on_finished)
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
                self.clog.toPlainText().strip(), self.token,
                src_path=self.src_le.text(),
                readme_path=self.readme_le.text(),
                vjson_path=self.vjson_le.text(),
                exe_path=self.exe_le.text(),
                tag_name=self.tag_le.text().strip() or ("v" + self.ver_le.text().strip()),
                release_name=f"GBFR Cooldown Indicator V{self.ver_le.text().strip()}",
                download_url=f"https://github.com/{REPO}/releases/download/v{self.ver_le.text().strip()}/" +
                             f"GBFR_CooldownIndicator_V{self.ver_le.text().strip().replace('.', '')}.exe",
                raw_url=self.src_url_le.text().strip(),
            )
            self.thread = threading.Thread(target=self.worker.run, daemon=True)
            self.worker.log.connect(self.log.appendPlainText)
            self.worker.need_token.connect(self._on_need_token)
            self.worker.finished.connect(self._on_finished)
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
