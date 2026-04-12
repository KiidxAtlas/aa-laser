"""Repository tab — git pull, commit, and push."""

from __future__ import annotations

import subprocess
import threading

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aa_laser.constants import _DIM
from aa_laser.settings import save_settings
from aa_laser.ui.helpers import _section_label


class RepoTab(QWidget):
    def __init__(self, parent: QWidget | None = None, settings: dict | None = None):
        super().__init__(parent)
        self._settings: dict = settings or {}

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        left_w = QWidget()
        left_w.setFixedWidth(300)
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        root.addWidget(left_w)

        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(4, 0, 0, 0)
        root.addWidget(right_w, stretch=1)

        self._build_left(left)
        self._build_right(right)

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left(self, layout: QVBoxLayout) -> None:
        _section_label(layout, "Repository")

        lbl = QLabel("Local path")
        lbl.setStyleSheet(f"color: {_DIM};")
        layout.addWidget(lbl)

        path_row = QHBoxLayout()
        self._repo_path = QLineEdit()
        self._repo_path.setPlaceholderText("Path to repo…")
        self._repo_path.setText(self._settings.get("repo_path", ""))
        path_row.addWidget(self._repo_path, stretch=1)
        browse_btn = QPushButton("…")
        browse_btn.setFixedSize(28, 28)
        browse_btn.clicked.connect(self._browse_repo)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        lbl2 = QLabel("Remote URL")
        lbl2.setStyleSheet(f"color: {_DIM};")
        layout.addWidget(lbl2)
        self._remote_url = QLineEdit()
        self._remote_url.setReadOnly(True)
        self._remote_url.setPlaceholderText(
            "(refreshed from git remote get-url origin)"
        )
        self._remote_url.setStyleSheet("color: #8b949e;")
        layout.addWidget(self._remote_url)

        # ── Status ────────────────────────────────────────────────────────────
        _section_label(layout, "Status")
        self._branch_label = QLabel("—")
        self._branch_label.setStyleSheet(f"color: {_DIM};")
        layout.addWidget(self._branch_label)
        self._commit_label = QLabel("")
        self._commit_label.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        self._commit_label.setWordWrap(True)
        layout.addWidget(self._commit_label)

        refresh_btn = QPushButton("↺  Refresh status")
        refresh_btn.setMinimumHeight(28)
        refresh_btn.clicked.connect(self._refresh_status)
        layout.addWidget(refresh_btn)

        # ── Sync ──────────────────────────────────────────────────────────────
        _section_label(layout, "Sync")
        self._pull_btn = QPushButton("⬇  Pull")
        self._pull_btn.setMinimumHeight(34)
        self._pull_btn.clicked.connect(self._pull)
        layout.addWidget(self._pull_btn)

        # ── Commit & Push ─────────────────────────────────────────────────────
        _section_label(layout, "Commit & Push")
        lbl3 = QLabel("Commit message")
        lbl3.setStyleSheet(f"color: {_DIM};")
        layout.addWidget(lbl3)
        self._commit_msg = QLineEdit()
        self._commit_msg.setPlaceholderText("Update patterns…")
        layout.addWidget(self._commit_msg)
        self._push_btn = QPushButton("⬆  Commit & Push")
        self._push_btn.setMinimumHeight(34)
        self._push_btn.setStyleSheet(
            "background: transparent;border: 1px solid #3fb950;color: #3fb950;"
        )
        self._push_btn.clicked.connect(self._push)
        layout.addWidget(self._push_btn)

        layout.addStretch()

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right(self, layout: QVBoxLayout) -> None:
        _section_label(layout, "Git Output")
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Menlo", 11))
        layout.addWidget(self._log, stretch=1)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _repo_dir(self) -> str | None:
        d = self._repo_path.text().strip()
        return d if d else None

    def _browse_repo(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select local repository folder")
        if d:
            self._repo_path.setText(d)
            self._settings["repo_path"] = d
            save_settings(self._settings)

    def _git(self, *args: str) -> tuple[int, str]:
        repo = self._repo_dir()
        if not repo:
            return 1, "No repository path set."
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = (result.stdout + result.stderr).strip()
            return result.returncode, out
        except FileNotFoundError:
            return 1, "git not found — is git installed and in PATH?"
        except subprocess.TimeoutExpired:
            return 1, "git command timed out."

    def _log_write(self, text: str) -> None:
        self._log.appendPlainText(text)

    def _log_clear(self) -> None:
        self._log.clear()

    def _set_btns(self, enabled: bool) -> None:
        self._pull_btn.setEnabled(enabled)
        self._push_btn.setEnabled(enabled)

    # ── Status ────────────────────────────────────────────────────────────────

    def _refresh_status(self) -> None:
        rc, branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if rc == 0:
            self._branch_label.setText(f"Branch: {branch}")
            self._branch_label.setStyleSheet("color: #3fb950;")
        else:
            self._branch_label.setText("Not a git repo")
            self._branch_label.setStyleSheet("color: #f85149;")
            self._commit_label.setText("")
            self._remote_url.setText("")
            return
        rc2, log = self._git("log", "--oneline", "-1")
        if rc2 == 0:
            self._commit_label.setText(log)
            self._commit_label.setStyleSheet(f"color: {_DIM};")
        rc3, remote = self._git("remote", "get-url", "origin")
        self._remote_url.setText(remote if rc3 == 0 else "")

    # ── Pull ──────────────────────────────────────────────────────────────────

    def _pull(self) -> None:
        self._set_btns(False)
        self._log_clear()
        threading.Thread(target=self._run_pull, daemon=True).start()

    def _run_pull(self) -> None:
        QTimer.singleShot(0, lambda: self._log_write("$ git pull"))
        rc, out = self._git("pull")
        QTimer.singleShot(0, lambda: self._log_write(out))
        if rc == 0:
            QTimer.singleShot(0, self._refresh_status)
        QTimer.singleShot(0, lambda: self._set_btns(True))

    # ── Push ──────────────────────────────────────────────────────────────────

    def _push(self) -> None:
        msg = self._commit_msg.text().strip() or "app commit"
        self._set_btns(False)
        self._log_clear()
        threading.Thread(target=self._run_push, args=(msg,), daemon=True).start()

    def _run_push(self, msg: str) -> None:
        QTimer.singleShot(0, lambda: self._log_write("$ git add -A"))
        rc, out = self._git("add", "-A")
        if out:
            QTimer.singleShot(0, lambda o=out: self._log_write(o))

        QTimer.singleShot(0, lambda: self._log_write(f'$ git commit -m "{msg}"'))
        rc, out = self._git("commit", "-m", msg)
        QTimer.singleShot(0, lambda o=out: self._log_write(o))
        if rc != 0 and "nothing to commit" not in out:
            QTimer.singleShot(0, lambda: self._set_btns(True))
            return

        QTimer.singleShot(0, lambda: self._log_write("$ git push"))
        rc, out = self._git("push")
        QTimer.singleShot(0, lambda o=out: self._log_write(o))
        if rc == 0:
            QTimer.singleShot(0, self._refresh_status)
            QTimer.singleShot(0, lambda: self._commit_msg.clear())
        QTimer.singleShot(0, lambda: self._set_btns(True))

    # ── Auto-pull on startup ──────────────────────────────────────────────────

    def auto_pull(self) -> None:
        """Called by App on startup. Only pulls if a repo path is configured."""
        if not self._repo_dir():
            return
        self._refresh_status()
        rc, remote = self._git("remote")
        if rc == 0 and remote.strip():
            threading.Thread(target=self._run_pull, daemon=True).start()
