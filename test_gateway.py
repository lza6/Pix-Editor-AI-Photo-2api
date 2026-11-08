import json, sys, urllib.request, urllib.error, ssl, time
sys.stdout.reconfigure(encoding='utf-8')
CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
def req(method, url, body=None, headers=None, timeout=320):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers: h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    t0=time.time()
    try:
        resp = urllib.request.urlopen(r, timeout=timeout, context=CTX)
        return resp.status, resp.read().decode(), round(time.time()-t0,1)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), round(time.time()-t0,1)
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}", round(time.time()-t0,1)

st, b, _ = req("GET", "http://127.0.0.1:18733/health")
print("health:", st, b[:220])
st, b, _ = req("GET", "http://127.0.0.1:18733/v1/models")
print("models:", st, b[:260])
st, b, _ = req("POST", "http://127.0.0.1:18733/v1/images/generations", {"prompt": "x"})
print("no-model ->", st, b[:150])
st, b, _ = req("POST", "http://127.0.0.1:18733/v1/images/generations", {"prompt": "x", "model": "bad"})
print("bad-model ->", st, b[:150])
st, b, _ = req("POST", "http://127.0.0.1:18733/v1/images/generations", {"prompt": "x", "model": "pix-editor-cheap", "image": "data:image/png;base64,notb64"})
print("bad-b64 ->", st, b[:150])
st, b, _ = req("POST", "http://127.0.0.1:18733/v1/images/generations", {"prompt": "x", "model": "pix-editor-cheap", "image": "http://127.0.0.1:9/x.jpg"})
print("ssrf-probe ->", st, b[:150])
st, b, dt = req("POST", "http://127.0.0.1:18733/v1/images/generations", {"prompt": "replace the background with a starry night sky over mountains", "model": "pix-editor-cheap"})
print(f"REAL cheap -> {st} in {dt}s")
print(" ", b[:420])
