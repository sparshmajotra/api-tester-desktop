# ui/main_window.py
"""
API Tester — Day 8..14 complete version
Features:
- Modern UI (customtkinter) with theme toggle
- Send GET/POST/PUT/DELETE requests (requests)
- Response tabs: Body (pretty JSON), Headers, Raw
- Response time measurement
- Save/export response (.json / .txt)
- Persistent request history stored in SQLite (optional JSON fallback)
- Ability to re-load history entries and re-run
- Threaded requests so UI doesn't freeze
- Basic logging to data/logs/app.log
- Packaging note: PyInstaller command included at the bottom
"""

import os
import json
import time
import threading
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
import requests
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

# -------------------------------
# CONFIG
# -------------------------------
USE_SQLITE = True   # set False to use JSON storage instead
DATA_DIR = Path("data")
DB_FILE = DATA_DIR / "history.db"
HISTORY_JSON = DATA_DIR / "history.json"
LOG_FILE = DATA_DIR / "logs" / "app.log"

# Ensure data dirs
DATA_DIR.mkdir(parents=True, exist_ok=True)
(LOG_FILE.parent).mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format="%(asctime)s %(levelname)s: %(message)s")

# -------------------------------
# Storage: SQLite helper (if enabled) or JSON fallback
# -------------------------------
def init_db():
    if not USE_SQLITE:
        return
    conn = sqlite3.connect(str(DB_FILE))
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        method TEXT,
        url TEXT,
        headers TEXT,
        body TEXT,
        status INTEGER,
        response_time REAL,
        timestamp TEXT
    )
    """)
    conn.commit()
    conn.close()

def save_history_entry(entry: dict):
    """entry: dict with method,url,headers,body,status,response_time,timestamp"""
    try:
        if USE_SQLITE:
            conn = sqlite3.connect(str(DB_FILE))
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO history (method,url,headers,body,status,response_time,timestamp) VALUES (?,?,?,?,?,?,?)",
                (entry.get("method"), entry.get("url"),
                 json.dumps(entry.get("headers", {}), ensure_ascii=False),
                 json.dumps(entry.get("body", ""), ensure_ascii=False) if isinstance(entry.get("body", ""), (dict, list)) else str(entry.get("body", "")),
                 entry.get("status"),
                 entry.get("response_time"),
                 entry.get("timestamp"))
            )
            conn.commit()
            conn.close()
        else:
            # JSON fallback
            data = []
            if HISTORY_JSON.exists():
                try:
                    data = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
                except Exception:
                    data = []
            data.append(entry)
            # keep last 200
            data = data[-200:]
            HISTORY_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logging.exception("Failed to save history: %s", e)

def load_history(n=200):
    items = []
    try:
        if USE_SQLITE:
            if not DB_FILE.exists():
                return []
            conn = sqlite3.connect(str(DB_FILE))
            cur = conn.cursor()
            cur.execute("SELECT id, method, url, headers, body, status, response_time, timestamp FROM history ORDER BY id DESC LIMIT ?", (n,))
            rows = cur.fetchall()
            conn.close()
            for r in rows:
                items.append({
                    "id": r[0],
                    "method": r[1],
                    "url": r[2],
                    "headers": json.loads(r[3]) if r[3] else {},
                    "body": try_json_load(r[4]),
                    "status": r[5],
                    "response_time": r[6],
                    "timestamp": r[7]
                })
        else:
            if not HISTORY_JSON.exists():
                return []
            data = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
            items = list(reversed(data[-n:]))  # most recent first
    except Exception as e:
        logging.exception("Failed to load history: %s", e)
    return items

def try_json_load(s):
    if not s:
        return ""
    try:
        return json.loads(s)
    except Exception:
        return s

def clear_history_storage():
    try:
        if USE_SQLITE:
            if DB_FILE.exists():
                conn = sqlite3.connect(str(DB_FILE))
                cur = conn.cursor()
                cur.execute("DELETE FROM history")
                conn.commit()
                conn.close()
        else:
            if HISTORY_JSON.exists():
                HISTORY_JSON.write_text("[]", encoding="utf-8")
    except Exception as e:
        logging.exception("Failed to clear history: %s", e)

# Initialize DB if using sqlite
if USE_SQLITE:
    init_db()

# -------------------------------
# UI
# -------------------------------
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class APITester(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("API Tester — Complete (Day8-14)")
        self.geometry("1200x760")
        self.minsize(1000, 650)

        # layout frames
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Left: history
        self.history_frame = ctk.CTkFrame(self, width=320)
        self.history_frame.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(12,6), pady=12)
        self.history_frame.grid_propagate(False)

        h_title = ctk.CTkLabel(self.history_frame, text="History", font=ctk.CTkFont(size=18, weight="bold"))
        h_title.pack(anchor="w", padx=12, pady=(12,6))

        # history controls
        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(self.history_frame, placeholder_text="Search history (method/url)...", textvariable=self.search_var)
        self.search_entry.pack(fill="x", padx=12, pady=(0,6))
        self.search_var.trace_add("write", lambda *_: self.populate_history())

        self.history_listbox = tk.Listbox(self.history_frame, height=24)
        self.history_listbox.pack(fill="both", expand=True, padx=12, pady=(0,6))
        self.history_listbox.bind("<<ListboxSelect>>", self.on_history_select)

        # history buttons
        hb = ctk.CTkFrame(self.history_frame, fg_color="transparent")
        hb.pack(fill="x", padx=12, pady=(0,12))
        ctk.CTkButton(hb, text="Reload", command=self.on_reload_history, width=90).pack(side="left", padx=6)
        ctk.CTkButton(hb, text="Clear", command=self.on_clear_history, width=90).pack(side="left", padx=6)
        ctk.CTkButton(hb, text="Use JSON", command=self.toggle_storage, width=90).pack(side="right", padx=6)

        # Right: request/response area
        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=0, column=1, sticky="new", padx=(6,12), pady=(12,6))
        top_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(top_frame, text="URL:", anchor="w").grid(row=0, column=0, padx=(8,6))
        self.url_entry = ctk.CTkEntry(top_frame, placeholder_text="https://api.example.com/endpoint")
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=(0,6))

        self.method_var = tk.StringVar(value="GET")
        self.method_menu = ctk.CTkOptionMenu(top_frame, values=["GET","POST","PUT","DELETE"], variable=self.method_var, width=110)
        self.method_menu.grid(row=0, column=2, padx=(0,8))

        self.send_btn = ctk.CTkButton(top_frame, text="🚀 Send Request (Ctrl+Enter)", command=self.on_send)
        self.send_btn.grid(row=0, column=3, padx=(0,8))

        # headers & body input
        mid_frame = ctk.CTkFrame(self)
        mid_frame.grid(row=1, column=1, sticky="nsew", padx=(6,12), pady=(6,12))
        mid_frame.grid_rowconfigure(2, weight=1)
        mid_frame.grid_columnconfigure(0, weight=1)

        hdr_label = ctk.CTkLabel(mid_frame, text="Headers (JSON):")
        hdr_label.grid(row=0, column=0, sticky="w", padx=8)
        self.headers_text = scrolledtext.ScrolledText(mid_frame, height=5, wrap="none")
        self.headers_text.grid(row=1, column=0, sticky="ew", padx=8, pady=(0,8))

        body_label = ctk.CTkLabel(mid_frame, text="Body (JSON / text):")
        body_label.grid(row=2, column=0, sticky="w", padx=8, pady=(0,4))
        self.body_text = scrolledtext.ScrolledText(mid_frame, height=8, wrap="none")
        self.body_text.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0,8))

        # Response area — use CTkTabview for tabs
        resp_frame = ctk.CTkFrame(self)
        resp_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0,12))
        resp_frame.grid_columnconfigure(0, weight=1)
        resp_frame.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(resp_frame)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.tabview.add("Body")
        self.tabview.add("Headers")
        self.tabview.add("Raw")

        # Body (pretty JSON if possible)
        self.body_resp = scrolledtext.ScrolledText(self.tabview.tab("Body"), wrap="none")
        self.body_resp.pack(fill="both", expand=True, padx=6, pady=6)

        # Headers
        self.headers_resp = scrolledtext.ScrolledText(self.tabview.tab("Headers"), wrap="none")
        self.headers_resp.pack(fill="both", expand=True, padx=6, pady=6)

        # Raw
        self.raw_resp = scrolledtext.ScrolledText(self.tabview.tab("Raw"), wrap="none")
        self.raw_resp.pack(fill="both", expand=True, padx=6, pady=6)

        # bottom controls: status, save/export, clear response
        bottom = ctk.CTkFrame(resp_frame, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=8, pady=(0,8))
        bottom.grid_columnconfigure(1, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ctk.CTkLabel(bottom, textvariable=self.status_var, anchor="w")
        self.status_label.grid(row=0, column=0, sticky="w", padx=(6,8))

        btn_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e", padx=8)

        ctk.CTkButton(btn_frame, text="Pretty JSON", command=self.pretty_print_response).pack(side="left", padx=6)
        ctk.CTkButton(btn_frame, text="📋 Copy", command=self.copy_response).pack(side="left", padx=6)
        ctk.CTkButton(btn_frame, text="💾 Save", command=self.save_response_dialog).pack(side="left", padx=6)
        ctk.CTkButton(btn_frame, text="Clear Response", command=self.clear_response).pack(side="left", padx=6)

        # keyboard shortcuts
        self.bind_all("<Control-Return>", lambda e: self.on_send())
        self.bind_all("<Control-s>", lambda e: self.save_response_dialog())
        self.bind_all("<Control-l>", lambda e: self.clear_response())
        self.bind_all("<Control-Shift-H>", lambda e: self.on_clear_history())

        # populate history initially
        self.populate_history()

    # -----------------------
    # UI Helper methods
    # -----------------------
    def toggle_storage(self):
        global USE_SQLITE
        USE_SQLITE = False if USE_SQLITE else True
        messagebox.showinfo("Storage switched", f"USE_SQLITE set to {USE_SQLITE}. Restart recommended.")
        logging_info = f"Storage toggled: USE_SQLITE={USE_SQLITE}"
        logging.info(logging_info)

    def on_reload_history(self):
        self.populate_history()

    def on_clear_history(self):
        if messagebox.askyesno("Clear history", "Are you sure you want to clear all history?"):
            clear_history_storage()
            self.populate_history()
            logging.info("User cleared history")
            self.status_var.set("History cleared")

    def populate_history(self):
        self.history_listbox.delete(0, tk.END)
        items = load_history(200)
        keyword = self.search_var.get().strip().lower()
        for it in items:
            text = f"{it.get('timestamp','')} - {it.get('method')} {it.get('url')[:60]}"
            if keyword and keyword not in text.lower():
                continue
            display_text = text if len(text) < 120 else text[:115] + "..."
            self.history_listbox.insert(tk.END, display_text)
        self.status_var.set(f"Loaded {self.history_listbox.size()} history items")

    def on_history_select(self, event):
        sel = self.history_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        items = load_history(200)
        # note: load_history returns most recent first
        if idx >= len(items):
            return
        entry = items[idx]
        # populate fields
        self.method_var.set(entry.get("method", "GET"))
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, entry.get("url", ""))
        # show headers and body nicely
        headers = entry.get("headers", {}) or {}
        try:
            hdr_text = json.dumps(headers, indent=2, ensure_ascii=False)
        except Exception:
            hdr_text = str(headers)
        self.headers_text.delete("1.0", tk.END)
        self.headers_text.insert("1.0", hdr_text)

        body = entry.get("body", "")
        try:
            if isinstance(body, (dict, list)):
                body_text = json.dumps(body, indent=2, ensure_ascii=False)
            else:
                body_text = str(body)
        except Exception:
            body_text = str(body)
        self.body_text.delete("1.0", tk.END)
        self.body_text.insert("1.0", body_text)
        self.status_var.set("Loaded from history (you can modify and re-send)")

    # -----------------------
    # Request & response
    # -----------------------
    def on_send(self):
        """Kick off threaded request to avoid freezing UI"""
        thread = threading.Thread(target=self._send_request_thread, daemon=True)
        thread.start()

    def _send_request_thread(self):
        url = self.url_entry.get().strip()
        method = self.method_var.get().upper()
        hdr_input = self.headers_text.get("1.0", tk.END).strip()
        body_input = self.body_text.get("1.0", tk.END).strip()

        if not url:
            messagebox.showwarning("Missing URL", "Please enter a URL before sending.")
            return

        # parse headers safely
        headers = {}
        if hdr_input:
            try:
                headers = json.loads(hdr_input)
                if not isinstance(headers, dict):
                    raise ValueError("Headers must be a JSON object")
            except Exception as e:
                self.safe_show_error("Invalid headers JSON", str(e))
                return

        # parse body optionally as JSON if possible
        body_for_req = None
        try:
            if body_input:
                body_for_req = json.loads(body_input)
        except Exception:
            body_for_req = body_input  # send as raw text if not JSON

        self.status_var.set("Sending...")
        start = time.perf_counter()
        try:
            # send request with requests.request to support all methods
            if method in ("GET", "DELETE"):
                resp = requests.request(method, url, headers=headers, timeout=30)
            else:
                # POST/PUT: if body is dict -> send json, else send data
                if isinstance(body_for_req, (dict, list)):
                    resp = requests.request(method, url, headers=headers, json=body_for_req, timeout=30)
                else:
                    resp = requests.request(method, url, headers=headers, data=body_for_req, timeout=30)

            elapsed = (time.perf_counter() - start) * 1000.0  # ms
            # attempt JSON pretty print
            try:
                body_pretty = json.dumps(resp.json(), indent=4, ensure_ascii=False)
            except Exception:
                body_pretty = resp.text

            # headers to JSON
            headers_pretty = json.dumps(dict(resp.headers), indent=4, ensure_ascii=False)

            # update UI on main thread
            self.after(0, lambda: self._update_response_ui(body_pretty, headers_pretty, resp.text, resp.status_code, elapsed))

            # save to history
            entry = {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body_for_req,
                "status": resp.status_code,
                "response_time": round(elapsed, 3),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            save_history_entry(entry)
            logging.info("%s %s -> %s (%.2f ms)", method, url, resp.status_code, elapsed)

            # reload history list
            self.after(0, lambda: self.populate_history())

        except requests.exceptions.RequestException as e:
            logging.exception("Request error: %s", e)
            self.safe_show_error("Request Error", str(e))
            self.after(0, lambda: self.status_var.set("Request Error"))

    def _update_response_ui(self, body_pretty, headers_pretty, raw_text, status_code, elapsed_ms):
        self.body_resp.delete("1.0", tk.END)
        self.body_resp.insert("1.0", body_pretty)
        self.headers_resp.delete("1.0", tk.END)
        self.headers_resp.insert("1.0", headers_pretty)
        self.raw_resp.delete("1.0", tk.END)
        self.raw_resp.insert("1.0", raw_text)
        self.status_var.set(f"Status {status_code} • {elapsed_ms:.2f} ms")
        # set color-like visual by changing text color: customtkinter label supports text_color
        if 200 <= status_code < 400:
            self.status_label.configure(text_color="#38b000")
        else:
            self.status_label.configure(text_color="#ff4d4d")

    # -----------------------
    # Response helpers
    # -----------------------
    def pretty_print_response(self):
        content = self.body_resp.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Empty", "No response to pretty-print.")
            return
        try:
            parsed = json.loads(content)
            pretty = json.dumps(parsed, indent=4, ensure_ascii=False)
            self.body_resp.delete("1.0", tk.END)
            self.body_resp.insert("1.0", pretty)
            self.tabview.set("Body")
            self.status_var.set("Pretty-printed JSON")
        except Exception:
            messagebox.showwarning("Not JSON", "Response body is not valid JSON.")

    def copy_response(self):
        text = self.body_resp.get("1.0", tk.END)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Response copied to clipboard")

    def save_response_dialog(self):
        content = self.body_resp.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("No response", "No response available to save.")
            return
        filetypes = [("JSON files","*.json"), ("Text files","*.txt")]
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=filetypes, title="Save response as")
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                # try to write pretty JSON if possible
                try:
                    parsed = json.loads(content)
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(parsed, f, indent=4, ensure_ascii=False)
                except Exception:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            self.status_var.set(f"Saved → {os.path.basename(path)}")
            messagebox.showinfo("Saved", f"Saved response to:\n{path}")
            logging.info("Saved response to %s", path)
        except Exception as e:
            logging.exception("Save failed: %s", e)
            messagebox.showerror("Save failed", str(e))

    def clear_response(self):
        self.body_resp.delete("1.0", tk.END)
        self.headers_resp.delete("1.0", tk.END)
        self.raw_resp.delete("1.0", tk.END)
        self.status_var.set("Cleared")

    def safe_show_error(self, title, message):
        # show error on main thread
        self.after(0, lambda: messagebox.showerror(title, message))

# -------------------------------
# Run
# -------------------------------
def main():
    app = APITester()
    app.mainloop()

if __name__ == "__main__":
    main()

# -------------------------------
# Packaging note (PyInstaller)
# -------------------------------
# After verifying everything works in your venv, install pyinstaller:
# pip install pyinstaller
#
# Then run (from project root):
# pyinstaller --noconsole --onefile --add-data "data;data" --icon=assets/app.ico -n "API Tester" ui/main_window.py
#
# On Windows the add-data string uses a semicolon "data;data". Adjust icon path or remove --icon if none.
# The built exe will be in dist\API Tester.exe
#
# Final testing checklist:
# - Run the exe on a machine without Python to verify everything bundled.
# - Check data/logs/app.log for logs.
# - Verify history persistence and save/export features.
