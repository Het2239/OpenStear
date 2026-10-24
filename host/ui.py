"""Desktop window: mode picker, QR code, connection status.

Tk runs on the main thread; the host's asyncio loop runs on a worker thread.
The window polls the host for status and sends mode changes to its loop.
"""

import asyncio
import tkinter as tk
from tkinter import ttk

import qrcode
from PIL import ImageTk

from .core import MODES, TETHER, USB, WIFI, HINTS

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
        self.status.configure(text="\n".join(lines))

        self.root.after(POLL_MS, self._poll)
