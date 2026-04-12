"""FVI → DXF conversion tab."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from aa_laser.core.fvi import convert_fvi_to_dxf
from aa_laser.ui.helpers import _section_label


class FviTab(ctk.CTkFrame):
    def __init__(self, master, settings: dict | None = None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._settings: dict = settings or {}
        self._last_out_dir: str | None = None

        left = ctk.CTkFrame(self, width=300)
        left.pack(side="left", fill="y", padx=(10, 4), pady=10)
        left.pack_propagate(False)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=10)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent: ctk.CTkFrame) -> None:
        _section_label(parent, "Mode")
        self._mode = ctk.StringVar(value="Single file")
        ctk.CTkSegmentedButton(
            parent,
            values=["Single file", "Folder (batch)"],
            variable=self._mode,
        ).pack(fill="x", padx=8, pady=(0, 4))

        _section_label(parent, "Source")
        src_row = ctk.CTkFrame(parent, fg_color="transparent")
        src_row.pack(fill="x", padx=8, pady=(0, 4))
        self._src_var = ctk.StringVar()
        ctk.CTkEntry(
            src_row,
            textvariable=self._src_var,
            placeholder_text="Select a .fvi file or folder…",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(src_row, text="Browse", width=70, command=self._browse_src).pack(
            side="right"
        )

        _section_label(parent, "Output folder")
        out_row = ctk.CTkFrame(parent, fg_color="transparent")
        out_row.pack(fill="x", padx=8, pady=(0, 4))
        self._out_var = ctk.StringVar()
        ctk.CTkEntry(
            out_row,
            textvariable=self._out_var,
            placeholder_text="Optional (blank = same as source)…",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(out_row, text="Browse", width=70, command=self._browse_out).pack(
            side="right"
        )

        self._btn = ctk.CTkButton(parent, text="Convert", height=38, command=self._run)
        self._btn.pack(fill="x", padx=8, pady=(14, 4))

        self._open_folder_btn = ctk.CTkButton(
            parent,
            text="Open Output Folder",
            height=28,
            fg_color="transparent",
            border_width=1,
            state="disabled",
            command=self._open_output_folder,
        )
        self._open_folder_btn.pack(fill="x", padx=8, pady=(0, 8))

    def _build_right(self, parent: ctk.CTkFrame) -> None:
        _section_label(parent, "Conversion Log", pady=(0, 4))
        self._log = ctk.CTkTextbox(parent, state="disabled", font=("Courier", 12))
        self._log.pack(fill="both", expand=True)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse_src(self) -> None:
        idir = self._settings.get("fvi_source_dir", "")
        if self._mode.get() == "Single file":
            path = filedialog.askopenfilename(
                title="Select FVI file",
                initialdir=idir or None,
                filetypes=[("FVI files", "*.fvi *.Fvi *.FVI"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askdirectory(
                title="Select folder containing FVI files",
                initialdir=idir or None,
            )
        if path:
            self._src_var.set(path)

    def _browse_out(self) -> None:
        idir = self._settings.get("fvi_output_dir", "")
        path = filedialog.askdirectory(
            title="Select output folder",
            initialdir=idir or None,
        )
        if path:
            self._out_var.set(path)

    def _log_write(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _log_clear(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _set_output_dir(self, d: str) -> None:
        self._last_out_dir = d
        self._open_folder_btn.configure(state="normal")

    def _open_output_folder(self) -> None:
        if self._last_out_dir:
            subprocess.run(["open", self._last_out_dir])

    def _run(self) -> None:
        src = self._src_var.get().strip()
        if not src:
            messagebox.showerror("Error", "Please select a source file or folder.")
            return
        self._btn.configure(state="disabled")
        self._log_clear()
        out_dir = self._out_var.get().strip() or None
        threading.Thread(target=self._convert, args=(src, out_dir), daemon=True).start()

    def _convert(self, src: str, out_dir: str | None) -> None:
        p = Path(src)
        if p.is_file():
            files = [p]
        else:
            raw = (
                list(p.rglob("*.fvi")) + list(p.rglob("*.Fvi")) + list(p.rglob("*.FVI"))
            )
            seen: set[str] = set()
            files = []
            for f in raw:
                k = str(f).lower()
                if k not in seen:
                    seen.add(k)
                    files.append(f)

        if not files:
            self.after(0, self._log_write, "No .fvi files found.")
            self.after(0, lambda: self._btn.configure(state="normal"))
            return

        self.after(0, self._log_write, f"Found {len(files)} file(s)\n")
        ok = err = 0
        for fvi in files:
            dest_dir = Path(out_dir) if out_dir else fvi.parent
            dest = dest_dir / fvi.with_suffix(".dxf").name
            try:
                convert_fvi_to_dxf(fvi, dest)
                self.after(0, self._log_write, f"  ✓  {fvi.name}  →  {dest.name}")
                ok += 1
            except Exception as exc:
                self.after(0, self._log_write, f"  ✗  {fvi.name}: {exc}")
                err += 1

        summary = f"\nDone — {ok} converted, {err} error(s)."
        self.after(0, self._log_write, summary)
        self.after(0, lambda: self._btn.configure(state="normal"))
        if files:
            final_dir = out_dir or str(files[0].parent)
            self.after(0, lambda d=final_dir: self._set_output_dir(d))
