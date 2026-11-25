#!/usr/bin/env python3
"""チャートをスマホ・タブレットから見るための簡易Webサーバー（標準ライブラリのみ）。

    python3 serve_charts.py            # 0.0.0.0:8080 で data/charts を公開
    python3 serve_charts.py 9000       # ポート指定

・ユーザー名/パスワードによるBasic認証つき（初回起動時に .chart_auth を自動生成）
・環境変数 CHART_USER / CHART_PASS でも指定できます
"""
import base64, http.server, os, secrets, socket, socketserver, sys, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, "data", "charts")
AUTH_FILE = os.path.join(BASE, ".chart_auth")


def get_credentials():
    user = os.environ.get("CHART_USER")
    pw = os.environ.get("CHART_PASS")
    if user and pw:
        return user, pw
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, encoding="utf-8") as fh:
            user, pw = fh.read().strip().split(":", 1)
        return user, pw
    user, pw = "chart", secrets.token_urlsafe(9)
    with open(AUTH_FILE, "w", encoding="utf-8") as fh:
        fh.write(f"{user}:{pw}")
    os.chmod(AUTH_FILE, 0o600)
    return user, pw


USER, PASS = get_credentials()
TOKEN = base64.b64encode(f"{USER}:{PASS}".encode()).decode()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        if not self._authorized():
            return
        if self.path in ("/", ""):
            self.path = "/index.html"
        super().do_GET()

    def do_HEAD(self):
        if self._authorized():
            super().do_HEAD()

    def _authorized(self):
        got = self.headers.get("Authorization", "")
        if got == "Basic " + TOKEN:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="kabu charts"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("認証が必要です\n".encode())
        return False

    def log_message(self, fmt, *args):   # アクセスログは静かめに
        if "40" in str(args[1] if len(args) > 1 else ""):
            super().log_message(fmt, *args)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    if not os.path.isdir(ROOT):
        sys.exit(f"チャートフォルダがありません: {ROOT}")
    n = len([f for f in os.listdir(ROOT) if f.endswith(".html")])
    print(f"公開フォルダ : {ROOT}（HTML {n}件）")
    print(f"同じWi-Fi内 : http://{lan_ip()}:{port}/")
    print(f"ユーザー名   : {USER}")
    print(f"パスワード   : {PASS}   （{AUTH_FILE} に保存）")
    print("停止する時は Control + C")
    with Server(("0.0.0.0", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n停止しました")
