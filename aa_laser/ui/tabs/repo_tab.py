"""Repository tab — git pull, commit, and push."""

from __future__ import annotations

import subprocess
import threading
from tkinter import filedialog

import customtkinter as ctk

from aa_laser.constants import _DIM
from aa_laser.settings import save_settings
from aa_laser.ui.helpers import _section_label


class RepoTab(ctk.CTkFrame):
    def __init__(self, master, settings: dict, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._settings = settings
        self._build()

    def _build(self) -> None:
        left = ctk.CTkFrame(self, width=300)
        left.pack(side="left", fill="y", padx=(10, 4), pady=10)
        left.pack_propagate(False)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=10)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent: ctk.CTkFrame) -> None:
        _section_label(parent, "Repository")

        ctk.CTkLabel(parent, text="Local path", anchor="w", text_color=_DIM).pack(
            anchor="w", padx=10
        )
        path_row = ctk.CTkFrame(parent, fg_color="transparent")
        path_row.pack(fill="x", padx=8, pady=(2, 4))
        self._repo_path = ctk.CTkEntry(path_row, placeholder_text="Path to repo…")
        self._repo_path.insert(0, self._settings.get("repo_path", ""))
        self._repo_path.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            path_row, text="…", width=28, height=28, command=self._browse_repo
        ).pack(side="right")

        ctk.CTkLabel(parent, text="Remote URL", anchor="w", text_color=_DIM).pack(
            anchor="w", padx=10
        )
        self._remote_url = ctk.CTkEntry(parent, placeholder_text="https://github.com/…")
        self._remote_url.insert(0, self._settings.get("repo_remote", ""))
        self._remote_url.pack(fill="x", padx=8, pady=(2, 4))

        _section_label(parent, "Status", pady=(8, 4))
        self._branch_label = ctk.CTkLabel(parent, text="—", anchor="w", text_color=_DIM)
        self._branch_label.pack(anchor="w", padx=10)
        self._commit_label = ctk.CTkLabel(
            parent,
            text="",
            anchor="w",
            text_color=_DIM,
            wraplength=270,
            font=("Helvetica", 11),
        )
        self._commit_label.pack(anchor="w", padx=10, pady=(2, 0))
        ctk.CTkButton(
            parent,
            text="↺  Refresh status",
            height=28,
            fg_color="transparent",
            border_width=1,
            command=self._refresh_status,
        ).pack(fill="x", padx=8, pady=(6, 0))

        _section_label(parent, "Sync")
        self._pull_btn = ctk.CTkButton(
            parent, text="⬇  Pull", height=34, command=self._pull
        )
        self._pull_btn.pack(fill="x", padx=8, pady=(0, 6))

        _section_label(parent, "Commit & Push")
        ctk.CTkLabel(parent, text="Commit message", anchor="w", text_color=_DIM).pack(
            anchor="w", padx=10
        )
        self._commit_msg = ctk.CTkEntry(parent, placeholder_text="Update patterns…")
        self._commit_msg.pack(fill="x", padx=8, pady=(2, 6))
        self._push_btn = ctk.CTkButton(
            parent,
            text="⬆  Commit & Push",
            height=34,
            fg_color="#1a5c1a",
            hover_color="#227722",
            command=self._push,
        )
        self._push_btn.pack(fill="x", padx=8, pady=(0, 6))

    def _build_right(self, parent: ctk.CTkFrame) -> None:
        _section_label(parent, "Git Output", padx=4, pady=(0, 4))
        self._log = ctk.CTkTextbox(parent, font=("Menlo", 11), state="disabled")
        self._log.pack(fill="both", expand=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _repo_dir(self) -> str | None:
        d = self._repo_path.get().strip()
        return d if d else None

    def _browse_repo(self) -> None:
        d = filedialog.askdirectory(title="Select local repository folder")
        if d:
            self._repo_path.delete(0, "end")
            self._repo_path.insert(0, d)
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
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _log_clear(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _set_btns(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._pull_btn.configure(state=state)
        self._push_btn.configure(state=state)

    # ── Status ────────────────────────────────────────────────────────────────

    def _refresh_status(self) -> None:
        rc, branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if rc == 0:
            self._branch_label.configure(text=f"Branch: {branch}", text_color="#60c060")
        else:
            self._branch_label.configure(text="Not a git repo", text_color="#e06060")
            self._commit_label.configure(text="")
            return
        rc2, log = self._git("log", "--oneline", "-1")
        if rc2 == 0:
            self._commit_label.configure(text=log, text_color=_DIM)

    # ── Pull ──────────────────────────────────────────────────────────────────

    def _pull(self) -> None:
        self._set_btns(False)
        self._log_clear()
        threading.Thread(target=self._run_pull, daemon=True).start()

    def _run_pull(self) -> None:
        self.after(0, self._log_write, "$ git pull")
        rc, out = self._git("pull")
        self.after(0, self._log_write, out)
        if rc == 0:
            self.after(0, self._refresh_status)
        self.after(0, self._set_btns, True)

    # ── Push ──────────────────────────────────────────────────────────────────

    def _push(self) -> None:
        msg = self._commit_msg.get().strip() or "app commit"
        self._set_btns(False)
        self._log_clear()
        threading.Thread(target=self._run_push, args=(msg,), daemon=True).start()

    def _run_push(self, msg: str) -> None:
        self.after(0, self._log_write, "$ git add -A")
        rc, out = self._git("add", "-A")
        if out:
            self.after(0, self._log_write, out)

        self.after(0, self._log_write, f'$ git commit -m "{msg}"')
        rc, out = self._git("commit", "-m", msg)
        self.after(0, self._log_write, out)
        if rc != 0 and "nothing to commit" not in out:
            self.after(0, self._set_btns, True)
            return

        self.after(0, self._log_write, "$ git push")
        rc, out = self._git("push")
        self.after(0, self._log_write, out)
        if rc == 0:
            self.after(0, self._refresh_status)
            self.after(0, lambda: self._commit_msg.delete(0, "end"))
        self.after(0, self._set_btns, True)

    # ── Auto-pull on startup ──────────────────────────────────────────────────

    def auto_pull(self) -> None:
        """Called by App on startup. Only pulls if a repo path is configured."""
        if not self._repo_dir():
            return
        self._refresh_status()
        rc, remote = self._git("remote")
        if rc == 0 and remote.strip():
            threading.Thread(target=self._run_pull, daemon=True).start()
