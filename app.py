"""Local GUI for browsing scraped rental listings.

Run with `python app.py`, then open http://127.0.0.1:5000 in a browser.
The "最新の情報を取得" button re-runs the SUUMO scraper in a background
thread; everything else (sorting, filtering) happens client-side against
the already-downloaded data, so no extra requests hit SUUMO while you browse.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import webbrowser

from flask import Flask, jsonify, render_template

from scraper import suumo

HOST = "127.0.0.1"
PORT = 5000

app = Flask(__name__)

_scrape_lock = threading.Lock()
_scrape_status = {"running": False, "message": "未取得です。「最新の情報を取得」を押してください。"}


def load_data() -> dict:
    if not suumo.DATA_PATH.exists():
        return {"scraped_at": None, "count": 0, "listings": []}
    with open(suumo.DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/listings")
def api_listings():
    return jsonify(load_data())


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    if _scrape_lock.locked():
        return jsonify({"ok": False, "message": "既に取得中です"}), 409

    def run() -> None:
        with _scrape_lock:
            _scrape_status["running"] = True
            _scrape_status["message"] = "取得中..."
            try:
                def progress(page: int, total: int) -> None:
                    _scrape_status["message"] = f"取得中... ({page}ページ目、{total}件)"

                listings = suumo.scrape_all(progress_cb=progress)
                suumo.save_listings(listings)
                _scrape_status["message"] = f"{len(listings)} 件取得しました"
            except Exception as e:  # noqa: BLE001 - surface any scrape failure to the GUI
                _scrape_status["message"] = f"エラー: {e}"
            finally:
                _scrape_status["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/scrape/status")
def api_scrape_status():
    status = dict(_scrape_status)
    status["running"] = _scrape_lock.locked()
    return jsonify(status)


def _open_browser_when_ready() -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.2):
                break
        except OSError:
            time.sleep(0.2)
    webbrowser.open(f"http://{HOST}:{PORT}/")


if __name__ == "__main__":
    # use_reloader=False: keeps this to a single process, so the
    # ready-check above only ever fires (and opens a browser tab) once.
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    app.run(host=HOST, port=PORT, debug=True, use_reloader=False)
