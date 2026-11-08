# -*- coding: utf-8 -*-
"""Pix Editor 2API gateway: Apero workflow x3 (cheap/expensive/i2v)."""
import json, time, random, base64, os, sys, threading, uuid, io
import urllib.request, urllib.error, ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")

PORT = int(os.environ.get("PIX_PORT", "18733"))
GATEWAY_KEY = os.environ.get("PIX_GATEWAY_KEY", "")
API_KEY = os.environ.get("PIX_APERO_API_KEY", "sk-REDACTED-SET-PIX_APERO_API_KEY-ENV")
BUNDLE = "com.snaptune.ai.photoeditor.collagemaker"
BASE = "https://api-img-gen-wrapper.apero.vn"
W_CHEAP = "067b0760-58e1-4033-addf-2ebb26498ed3"
W_EXP = "edb8925c-f39c-4c43-b41d-7917b2efe19b"
W_I2V = "3e28e0b0-9233-45ca-85fb-c01691080106"
MAX_CONC = int(os.environ.get("PIX_MAX_CONC", "4"))
POLL_INTERVAL = 4
POLL_MAX = 75

MODEL_MAP = {
    "pix-editor-cheap": ("i2i", W_CHEAP),
    "pix-editor-expensive": ("i2i", W_EXP),
    "pix-editor-i2v": ("i2v", W_I2V),
}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
SEM = threading.Semaphore(MAX_CONC)
STATS = {"total": 0, "ok": 0, "err": 0, "in_flight": 0, "started": time.time()}
STATS_LOCK = threading.Lock()

RSA_PUB_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5z8DrSdxAFy5ju27JzxU
DGD5OdPRnKVrXPypiBVT7NK4ltgbcud3+Li3H1DiAFNvaSDPumZMEbAkfGWZ6s3K
tiI7TRmZwQ2yyH6mug6GhrCLD6CZJUQ2CPmhO3JYTYOgN53E6hwm/Teb9I156S04
qHjLLLBxk9Mklu5X06kdhMBYwHFAZ3oByeoWUryrQC0Mv9C5ZahKzoQNuJNL2sv+
ws2e5Zaj8Rid4AjhvqB6dYhWP4QM+0IiNjs/j08aRgcyOrenbQEIieU+XF6mQWF2
Jfg317e0KjWnpru+uPVVgrEn9rNvQeXu2u4SZhT6rnLQzBLbJrngNcNw3gXfxxso
owIDAQAB
-----END PUBLIC KEY-----"""

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric import padding as apadding
_PUB = load_pem_public_key(RSA_PUB_PEM.encode())


def http_req(method, url, headers=None, body=None, timeout=90):
    """body: dict -> JSON + CT; bytes -> raw; None -> no payload."""
    h = {"User-Agent": "okhttp/4.9.3"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        else:
            data = body
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=timeout, context=CTX)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return -1, str(e).encode()


def apero_headers():
    ts = int(time.time() * 1000)
    payload = "%d@@@%s@@@%d" % (ts, API_KEY, random.randint(0, 999999))
    sig = base64.b64encode(_PUB.encrypt(payload.encode(), apadding.PKCS1v15())).decode()
    return {
        "app-name": "x",
        "x-api-token": "not_get_api_token",
        "x-api-signature": sig,
        "x-api-timestamp": str(ts),
        "x-api-bundleid": BUNDLE,
        "x-api-keyid": "1",
        "country-code": "US",
        "app-version": "1.4.51",
        "Accept": "application/json",
    }


def make_jpeg(prompt_seed=0):
    """512x512 test JPEG (placeholder for real user image)."""
    from PIL import Image
    img = Image.new("RGB", (512, 512), (30 + prompt_seed % 60, 90, 200))
    for x in range(512):
        for y in range(0, 512, 50):
            img.putpixel((x, y), (255, 200, 0))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def upload_image(jpeg_bytes):
    """presigned-link -> S3 PUT -> bare s3 path"""
    st, body = http_req("GET", BASE + "/api/v5.1/qwen-editing/presigned-link", apero_headers())
    if st != 200:
        raise RuntimeError("presigned %s: %s" % (st, body[:200]))
    d = json.loads(body)["data"]
    st2, _ = http_req("PUT", d["url"], {"Content-Type": "image/jpg"}, jpeg_bytes)
    if st2 != 200:
        raise RuntimeError("s3 PUT %s" % st2)
    return d["path"]


def run_workflow(wid, inp):
    st, body = http_req("POST", BASE + "/api/v1/workflow/execute", apero_headers(),
                        {"workflowId": wid, "input": inp})
    if st not in (200, 201):
        raise RuntimeError("execute %s: %s" % (st, body[:200]))
    return json.loads(body)["runId"]


def poll_workflow(rid, deadline_s=300):
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        time.sleep(POLL_INTERVAL)
        st, body = http_req("GET", BASE + "/api/v1/workflow/execute/" + rid, apero_headers())
        if st != 200:
            continue
        try:
            j = json.loads(body)
        except Exception:
            continue
        status = j.get("status")
        if status in ("success", "failed"):
            return j
    return {"status": "timeout", "runId": rid}


def generate(model, prompt, image_bytes, extra=None):
    """full pipeline -> {"status", "result_url", "runId"}"""
    t0 = time.time()
    kind, wid = MODEL_MAP[model]
    jpeg = image_bytes or make_jpeg(len(prompt or ""))
    s3path = upload_image(jpeg)
    if kind == "i2i":
        inp = {"files": [s3path], "prompt": prompt or ""}
    else:
        inp = {"files": [s3path], "mode": "i2v", "model": (extra or {}).get("video_model", "seedance-lite"),
               "positivePrompt": prompt or "", "backgroundPrompt": (extra or {}).get("background_prompt", "")}
    rid = run_workflow(wid, inp)
    j = poll_workflow(rid)
    out = j.get("output") or {}
    url = out.get("resultFile")
    if isinstance(url, list):
        url = url[0] if url else None
    return {"status": j.get("status"), "result_url": url, "runId": rid,
            "elapsed": round(time.time() - t0, 1)}
