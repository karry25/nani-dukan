"""Dev helper: drive headless Chrome over CDP and screenshot each page (mock model)."""
import base64, json, subprocess, sys, threading, time, urllib.request, tempfile
import websocket
from server import serve
from nanidukan.llm import MockClient
srv, svc = serve(port=8123, db_path=":memory:", llm=MockClient())
threading.Thread(target=srv.serve_forever, daemon=True).start()
ch = subprocess.Popen(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=9333",
                       "--window-size=1280,800", "--user-data-dir=" + tempfile.mkdtemp(), "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)
tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
_id = 0
def cmd(m, **p):
    global _id; _id += 1; ws.send(json.dumps({"id": _id, "method": m, "params": p}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == _id: return r.get("result", {})
def js(e): return cmd("Runtime.evaluate", expression=e, awaitPromise=True, returnByValue=True).get("result", {}).get("value")
def shot(name):
    d = cmd("Page.captureScreenshot", format="png")["data"]; open(f"/downloads/{name}.png", "wb").write(base64.b64decode(d))
cmd("Page.enable"); cmd("Page.navigate", url="http://127.0.0.1:8123/"); time.sleep(1.5)
shot("ui_login")
js("[...document.querySelectorAll('button')].find(b=>b.textContent=='Try demo').click()"); time.sleep(2)
errs = []
def nav(label):
    js(f"[...document.querySelectorAll('.nav')].find(n=>n.textContent.startsWith({json.dumps(label)})).click()"); time.sleep(1.2)
def setv(sel, v): js(f"(()=>{{const e=document.querySelector({json.dumps(sel)});e.value={json.dumps(v)}}})()")
def click(txt): js(f"[...document.querySelectorAll('button')].find(b=>b.textContent=={json.dumps(txt)}).click()"); time.sleep(1.2)
nav("Tonight"); setv("textarea", "aaj sale 5200, kharcha 800, cash 6100, thread khatam, Anjali ne 300 diye"); click("Read my note"); shot("ui_checkin")
nav("Customer"); setv("textarea", "didi jhumka ka price kitna hai? urgent chahiye kal tak"); click("Draft a reply"); shot("ui_chats")
nav("Udhaar"); shot("ui_udhaar")
nav("Bills"); setv("textarea", "Sharma Traders 12/11/2026 total Rs 2400 stock"); click("Sort these"); setv("textarea", "blurry"); click("Sort these"); shot("ui_bills")
nav("Month"); time.sleep(1); shot("ui_month")
nav("Activity"); shot("ui_activity")
print("body text length", js("document.body.innerText.length"))
ch.terminate(); srv.shutdown()
