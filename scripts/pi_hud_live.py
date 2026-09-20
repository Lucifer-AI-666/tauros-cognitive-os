#!/usr/bin/env python3
"""JARVIS HUD — Groq + SSE live telemetry. Standard library only."""
from __future__ import annotations

import json
import os
import platform
import sys
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST = os.environ.get("HUD_HOST", "0.0.0.0")
PORT = int(os.environ.get("HUD_PORT", "7071"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

ROOT = Path(__file__).resolve().parent / "hud"


def _cpu_percent() -> float:
    if sys.platform.startswith("linux"):
        def snap():
            with open("/proc/stat", encoding="utf-8") as f:
                p = f.readline().split()
            idle = int(p[4]) + int(p[5])
            total = sum(int(x) for x in p[1:])
            return idle, total

        i1, t1 = snap()
        time.sleep(0.08)
        i2, t2 = snap()
        dt, di = (t2 - t1), (i2 - i1)
        if dt <= 0:
            return 0.0
        return round(max(0.0, min(100.0, (1 - di / dt) * 100)), 1)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

            def ticks(ft: FILETIME) -> int:
                return (ft.dwHighDateTime << 32) + ft.dwLowDateTime

            idle = FILETIME()
            kernel = FILETIME()
            user = FILETIME()
            Get = ctypes.windll.kernel32.GetSystemTimes
            Get(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            a = ticks(idle), ticks(kernel), ticks(user)
            time.sleep(0.08)
            Get(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            b = ticks(idle), ticks(kernel), ticks(user)
            idle_d = b[0] - a[0]
            tot_d = (b[1] - a[1]) + (b[2] - a[2])
            if tot_d <= 0:
                return 0.0
            return round(max(0.0, min(100.0, (1 - idle_d / tot_d) * 100)), 1)
        except OSError:
            return 0.0
    return 0.0


def _ram_percent() -> float:
    if sys.platform.startswith("linux"):
        info: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                key, rest = line.split(":", 1)
                info[key] = int(rest.strip().split()[0])
        total = info.get("MemTotal", 1)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        return round(max(0.0, min(100.0, (1 - avail / total) * 100)), 1)
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return float(stat.dwMemoryLoad)
        except OSError:
            return 0.0
    return 0.0


def _temp_c() -> float:
    if sys.platform.startswith("linux"):
        candidates = [
            Path("/sys/class/thermal/thermal_zone0/temp"),
            Path("/sys/class/hwmon/hwmon0/temp1_input"),
        ]
        for p in candidates:
            try:
                raw = int(p.read_text().strip())
                return round(raw / 1000.0 if raw > 200 else float(raw), 1)
            except (OSError, ValueError):
                continue
    return 0.0


WINDOW = 15  # secondi tra una chiamata Groq e la successiva → 4/min
TEMP_SPIKE_C = 5.0
TEMP_WARN_C = 70.0


def status() -> dict:
    return {
        "cpu": _cpu_percent(),
        "ram": _ram_percent(),
        "temp": _temp_c(),
        "host": platform.node(),
        "ts": time.time(),
    }


def fold_window(samples: list[dict]) -> dict:
    """Fonde 15 letture locali in un unico pacchetto per Groq (4 volte al minuto)."""
    last = samples[-1]
    temps = [s["temp"] for s in samples]
    cpus = [s["cpu"] for s in samples]
    rams = [s["ram"] for s in samples]
    t0, t1 = temps[0], temps[-1]
    peak = max(temps)
    delta = round(t1 - t0, 1)
    spike = delta >= TEMP_SPIKE_C or peak >= TEMP_WARN_C
    return {
        **last,
        "cpu_avg": round(sum(cpus) / len(cpus), 1),
        "cpu_peak": round(max(cpus), 1),
        "ram_peak": round(max(rams), 1),
        "temp_start": t0,
        "temp_peak": peak,
        "temp_delta": delta,
        "spike": spike,
        "samples": len(samples),
    }


def get_groq_verdict(stats: dict) -> str:
    if not GROQ_API_KEY:
        if stats.get("spike"):
            return (
                f"WARNING locale: temp {stats['temp']}°C "
                f"(Δ {stats.get('temp_delta', 0):+}°C in {WINDOW}s). Groq offline."
            )
        return "Modalità offline. Chiave Groq mancante."
    spike_line = ""
    if stats.get("spike"):
        spike_line = (
            " ALLARME TERMICO: la temperatura è salita di colpo. "
            "Inizia la frase con WARNING."
        )
    prompt = (
        "Sei JARVIS. Analizza questi dati hardware in tempo reale e fornisci un verdetto "
        "di stato in una singola frase (max 20 parole), cinico ma professionale."
        f"{spike_line} "
        f"CPU ora {stats['cpu']}% (media {stats.get('cpu_avg', stats['cpu'])}%, "
        f"picco {stats.get('cpu_peak', stats['cpu'])}%), "
        f"RAM {stats['ram']}% (picco {stats.get('ram_peak', stats['ram'])}%), "
        f"Temp ora {stats['temp']}°C, picco {stats.get('temp_peak', stats['temp'])}°C, "
        f"delta {stats.get('temp_delta', 0):+}°C negli ultimi {stats.get('samples', WINDOW)} secondi."
    )
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
        "temperature": 0.7,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GROQ_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Interferenza di rete spaziale: {e}"


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed_path = urlparse(self.path).path
        # --- MODALITÀ LIVE (Server-Sent Events) ---
        if parsed_path == "/api/live":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            counter = 0
            last_verdict = "Inizializzazione sensori neurali..."
            window: list[dict] = []
            try:
                while True:
                    current_stats = status()
                    window.append(current_stats)
                    # Silicio: 60 letture/min. Cloud: 4 verdetti/min (ogni 15 campioni).
                    if counter % WINDOW == 0:
                        folded = fold_window(window or [current_stats])
                        last_verdict = get_groq_verdict(folded)
                        window = [current_stats]
                    current_stats["verdict"] = last_verdict
                    current_stats["api_rpm"] = 60 // WINDOW
                    sse_data = f"data: {json.dumps(current_stats)}\n\n"
                    self.wfile.write(sse_data.encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(1)
                    counter += 1
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError, OSError):
                pass
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        return


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"JARVIS HUD LIVE  http://{HOST}:{PORT}/  SSE /api/live  groq={bool(GROQ_API_KEY)} model={GROQ_MODEL}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstop")


if __name__ == "__main__":
    main()
