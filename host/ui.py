"""Desktop window: mode picker, QR code, connection status.

Tk runs on the main thread; the host's asyncio loop runs on a worker thread.
The window polls the host for status and sends mode changes to its loop.
"""

import asyncio
import tkinter as tk
from tkinter import ttk

import qrcode
from PIL import ImageTk

from .core import MODES, TETHER, USB, WIFI, HINTS, running_programs
from .profiles import AUTO, OFF

QR_PX = 260
POLL_MS = 300


class Window:
    def __init__(self, host, loop, on_mode_change=None):
        self.host = host
        self.loop = loop
        self.on_mode_change = on_mode_change
        self._url = object()  # forces the first QR render
        self._qr_img = None
        self._choices = []

        root = self.root = tk.Tk()
        root.title("OpenSteer")
        root.resizable(False, False)
        frame = ttk.Frame(root, padding=16)
        frame.grid(sticky="nsew")

        ttk.Label(frame, text="OpenSteer", font=("TkDefaultFont", 16, "bold")).grid(sticky="w")

        modes = ttk.Frame(frame)
        modes.grid(sticky="w", pady=(10, 4))
        self.mode_var = tk.StringVar(value=host.mode)
        for i, mode in enumerate((USB, TETHER, WIFI)):
            ttk.Radiobutton(modes, text=MODES[mode], value=mode, variable=self.mode_var,
                            command=self._mode_clicked).grid(row=0, column=i, padx=(0, 12))

        self.net_row = ttk.Frame(frame)
        self.net_row.grid(sticky="we", pady=4)
        ttk.Label(self.net_row, text="Network:").grid(row=0, column=0, padx=(0, 6))
        self.net_var = tk.StringVar()
        self.net_box = ttk.Combobox(self.net_row, textvariable=self.net_var, state="readonly", width=40)
        self.net_box.grid(row=0, column=1, sticky="we")
        self.net_box.bind("<<ComboboxSelected>>", self._net_selected)

        # A blank image keeps the label QR-sized (in pixels) when there is no link.
        self._blank = tk.PhotoImage(width=QR_PX, height=QR_PX)
        self.qr = tk.Label(frame, image=self._blank, compound="center", bg="white")
        self.qr.grid(pady=8)

        url_row = ttk.Frame(frame)
        url_row.grid(sticky="we")
        self.url_var = tk.StringVar()
        ttk.Entry(url_row, textvariable=self.url_var, state="readonly", width=44).grid(row=0, column=0)
        ttk.Button(url_row, text="Copy", command=self._copy).grid(row=0, column=1, padx=(6, 0))

        self.hint = ttk.Label(frame, wraplength=QR_PX + 120, justify="left")
        self.hint.grid(sticky="w", pady=(10, 0))
        self.problem = ttk.Label(frame, wraplength=QR_PX + 120, justify="left", foreground="#c0392b")
        self.problem.grid(sticky="w", pady=(6, 0))
        self.status = ttk.Label(frame, justify="left")
        self.status.grid(sticky="w", pady=(10, 0))

        # Game profiles: layouts saved from a phone, optionally tied to a game.
        prof = ttk.LabelFrame(frame, text="Game profile", padding=8)
        prof.grid(sticky="we", pady=(12, 0))
        self.profile_var = tk.StringVar()
        self.profile_box = ttk.Combobox(prof, textvariable=self.profile_var, state="readonly", width=30)
        self.profile_box.grid(row=0, column=0, sticky="we")
        self.profile_box.bind("<<ComboboxSelected>>", self._profile_selected)
        ttk.Button(prof, text="Manage...", command=self._manage_profiles).grid(row=0, column=1, padx=(6, 0))
        self.profile_info = ttk.Label(prof, wraplength=QR_PX + 100, justify="left")
        self.profile_info.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._profile_choices = []

        root.after(0, self._poll)

    def run(self):
        self.root.mainloop()

    def _call(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _mode_clicked(self):
        mode = self.mode_var.get()
        self._call(self.host.set_mode(mode))
        if self.on_mode_change:
            self.on_mode_change(mode)

    def _net_selected(self, _event):
        i = self.net_box.current()
        if 0 <= i < len(self._choices):
            self._call(self.host.set_mode(self.host.mode, self._choices[i].ip))

    # --- profiles ----------------------------------------------------------

    def _profile_selected(self, _event):
        i = self.profile_box.current()
        if 0 <= i < len(self._profile_choices):
            self._call(self.host.select_profile(self._profile_choices[i][0]))

    def _render_profiles(self):
        p = self.host.profiles
        choices = [(OFF, "Off (phones use their own layout)"), (AUTO, "Auto (when its game is running)")]
        choices += [(n, f"Always: {n}") for n in p.names()]
        if choices != self._profile_choices:
            self._profile_choices = choices
            self.profile_box["values"] = [c[1] for c in choices]
        sel = next((i for i, c in enumerate(choices) if c[0] == p.selection), 1)
        if self.profile_box.current() != sel:
            self.profile_box.current(sel)
        active = p.active()
        if active:
            exe = p.profiles[active].get("exe")
            info = f"Active: {active}" + (f" ({exe} is running)" if p.selection == AUTO and exe else "")
        elif not p.names():
            info = "No profiles yet. On the phone: Layout menu > Save to PC as profile."
        elif p.selection == AUTO:
            info = "No linked game running. Link profiles to games under Manage..."
        else:
            info = "Off"
        self.profile_info.configure(text=info)

    def _manage_profiles(self):
        ProfileManager(self.root, self.host, self._call)

    def _copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url_var.get())

    def _poll(self):
        host = self.host
        url = host.url()
        if url != self._url:
            self._url = url
            self.url_var.set(url or "")
            if url:
                img = qrcode.make(url, border=2).resize((QR_PX, QR_PX))
                self._qr_img = ImageTk.PhotoImage(img)
                self.qr.configure(image=self._qr_img, text="")
            else:
                self._qr_img = None
                self.qr.configure(image=self._blank, text="No link for this mode yet")

        choices = host.ip_choices()
        if choices != self._choices:
            self._choices = choices
            self.net_box["values"] = [c.label for c in choices]
        current = host.current_ip()
        for i, c in enumerate(choices):
            if c.ip == current and self.net_box.current() != i:
                self.net_box.current(i)
        if host.mode == USB or not choices:
            self.net_row.grid_remove()
        else:
            self.net_row.grid()

        self.hint.configure(text=HINTS[host.mode])
        self.problem.configure(text=host.problem() or "")

        lines = [f"Phones connected: {len(host.phones())}"]
        if host.mode == USB:
            devices = host.adb_status["devices"]
            if not devices and host.adb_status["adb"]:
                lines.append("USB: no Android phone detected")
            for serial, state in devices.items():
                text = {"ready": "ready", "unauthorized": "accept the USB debugging prompt on the phone"}
                lines.append(f"USB {serial}: {text.get(state, state)}")
        if host.telemetry is not None:
            lines.append(host.telemetry.status())
        self.status.configure(text="\n".join(lines))
        self._render_profiles()

        self.root.after(POLL_MS, self._poll)


class ProfileManager:
    """Small window: link profiles to games, delete them."""

    def __init__(self, parent, host, call):
        self.host = host
        self.call = call
        top = self.top = tk.Toplevel(parent)
        top.title("Game profiles")
        top.resizable(False, False)
        f = ttk.Frame(top, padding=12)
        f.grid()
        self.listbox = tk.Listbox(f, width=46, height=8, exportselection=False)
        self.listbox.grid(row=0, column=0, columnspan=3, sticky="we")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._selected())

        ttk.Label(f, text="Game program:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.exe_var = tk.StringVar()
        self.exe_box = ttk.Combobox(f, textvariable=self.exe_var, width=28)
        self.exe_box.grid(row=1, column=1, sticky="we", pady=(10, 0))
        ttk.Button(f, text="Refresh", command=self._refresh_programs).grid(row=1, column=2, padx=(6, 0), pady=(10, 0))
        ttk.Label(f, text="Start the game, then pick its program here (e.g. F1_25.exe).",
                  foreground="#666").grid(row=2, column=0, columnspan=3, sticky="w")

        row = ttk.Frame(f)
        row.grid(row=3, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(row, text="Link to game", command=self._link).grid(row=0, column=0)
        ttk.Button(row, text="Unlink", command=self._unlink).grid(row=0, column=1, padx=6)
        ttk.Button(row, text="Delete profile", command=self._delete).grid(row=0, column=2)
        ttk.Button(row, text="Close", command=top.destroy).grid(row=0, column=3, padx=(6, 0))
        self._refresh()
        self._refresh_programs()

    def _names(self):
        return self.host.profiles.names()

    def _current(self):
        sel = self.listbox.curselection()
        names = self._names()
        return names[sel[0]] if sel and sel[0] < len(names) else None

    def _refresh(self, keep=None):
        self.listbox.delete(0, "end")
        for n in self._names():
            exe = self.host.profiles.profiles[n].get("exe")
            self.listbox.insert("end", f"{n}   ({exe or 'not linked'})")
        if keep in self._names():
            self.listbox.selection_set(self._names().index(keep))

    def _refresh_programs(self):
        self.exe_box["values"] = sorted(running_programs())

    def _selected(self):
        name = self._current()
        if name:
            self.exe_var.set(self.host.profiles.profiles[name].get("exe") or "")

    def _link(self):
        name = self._current()
        if name and self.exe_var.get().strip():
            self.call(self.host.link_profile(name, self.exe_var.get().strip()))
            self.top.after(150, lambda: self._refresh(name))

    def _unlink(self):
        name = self._current()
        if name:
            self.call(self.host.link_profile(name, None))
            self.top.after(150, lambda: self._refresh(name))

    def _delete(self):
        name = self._current()
        if name:
            self.call(self.host.delete_profile(name))
            self.top.after(150, self._refresh)
