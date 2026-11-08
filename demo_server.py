# -*- coding: utf-8 -*-
"""Pix Editor 2API gateway HTTP layer (OpenAI images API subset)."""
import json, time, base64, os, sys, threading, urllib.parse, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import (PORT, GATEWAY_KEY, MODEL_MAP, MAX_CONC, SEM, STATS, STATS_LOCK,
                  generate, upload_image, make_jpeg, http_req, apero_headers, BASE)

sys.stdout.reconfigure(encoding="utf-8")


def error_body(code, msg, etype="invalid_request_error"):
    return {"error": {"message": msg, "type": etype, "code": code}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass

    # ---------- helpers ----------
    def _send(self, status, payload, ctype="application/json"):
        b = json.dumps(payload, ensure_ascii=False).encode() if not isinstance(payload, bytes) else payload
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _auth(self):
        if not GATEWAY_KEY:
            return True
        a = self.headers.get("Authorization", "")
        return a == "Bearer " + GATEWAY_KEY

    def _read_body(self, limit=8 * 1024 * 1024):
        ln = int(self.headers.get("Content-Length") or 0)
        if ln > limit:
            raise ValueError("body too large")
        raw = self.rfile.read(ln) if ln else b""
        if not raw:
            return {}
        ct = (self.headers.get("Content-Type") or "").lower()
        if "json" in ct:
            j = json.loads(raw)
            if not isinstance(j, dict):
                raise ValueError("JSON body must be an object")
            return j
        if "form-data" in ct or "x-www-form-urlencoded" in ct:
            return {"_form": raw, "_ct": ct}
        return {"_raw": raw, "_ct": ct}

    # ---------- routes ----------
    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/health":
            return self._send(200, {"ok": True, "models": sorted(MODEL_MAP),
                                    "max_conc": MAX_CONC, "stats": STATS})
        if p == "/v1/models":
            return self._send(200, {"object": "list", "data": [
                {"id": m, "object": "model", "owned_by": "pix-editor"} for m in MODEL_MAP]})
        if p in ("/", "/demo", "/demo.html"):
            fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.html")
            with open(fp, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if p == "/favicon.ico":
            # 1x1 透明 PNG
            png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89" + b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4" + b"\x00\x00\x00\x00IEND\xaeB`\x82"
            return self._send(200, png, "image/png")
        return self._send(404, error_body("not_found", p))

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if not self._auth():
            return self._send(401, error_body("invalid_api_key", "missing/wrong bearer"))
        if p not in ("/v1/images/generations", "/v1/images/edits"):
            return self._send(404, error_body("not_found", p))

        try:
            body = self._read_body()
        except ValueError as e:
            return self._send(413 if "too large" in str(e) else 400, error_body("bad_body", str(e)))
        except Exception as e:
            return self._send(400, error_body("bad_json", str(e)))

        # 提取参数: JSON 或 multipart
        prompt = ""
        model = "pix-editor-cheap"
        image_bytes = None
        extra = {}
        if "_form" in body:
            # 简易 multipart 解析
            import re
            ct = body["_ct"]
            m = re.search(r"boundary=(.+)", ct)
            if not m:
                return self._send(400, error_body("bad_body", "no boundary"))
            boundary = m.group(1).encode()
            for part in body["_form"].split(b"--" + boundary):
                if b"Content-Disposition" not in part:
                    continue
                hd, _, val = part.partition(b"\r\n\r\n")
                val = val.rsplit(b"\r\n", 1)[0]
                nm = re.search(rb'name="([^"]+)"', hd)
                fn = re.search(rb'filename="([^"]+)"', hd)
                if not nm:
                    continue
                name = nm.group(1).decode()
                if fn and fn.group(1):
                    image_bytes = val
                elif name == "prompt":
                    prompt = val.decode("utf-8", "replace")
                elif name == "model":
                    model = val.decode()
                elif name == "background_prompt":
                    extra["background_prompt"] = val.decode()
                elif name == "video_model":
                    extra["video_model"] = val.decode()
        else:
            prompt = str(body.get("prompt") or "")
            model = str(body.get("model") or model)
            extra = {"background_prompt": str(body.get("background_prompt") or ""),
                     "video_model": str(body.get("video_model") or "seedance-lite")}
            img = body.get("image")
            if isinstance(img, str):
                if img.startswith("data:image"):
                    parts = img.split(",", 1)
                    if len(parts) != 2:
                        return self._send(400, error_body("bad_image", "malformed data URI"))
                    try:
                        image_bytes = base64.b64decode(parts[1])
                    except Exception:
                        return self._send(400, error_body("bad_image", "bad base64"))
                elif img.startswith("http"):
                    st, raw = http_req("GET", img, timeout=30)
                    if st != 200:
                        return self._send(400, error_body("bad_image", "fetch %s" % st))
                    image_bytes = raw

        if model not in MODEL_MAP:
            return self._send(400, error_body("bad_model", "model must be one of " + ",".join(MODEL_MAP)))
        # 校验图片可解码
        if image_bytes:
            try:
                import io
                from PIL import Image
                im = Image.open(io.BytesIO(image_bytes)); im.verify()
                im2 = Image.open(io.BytesIO(image_bytes)); im2.load()
            except Exception:
                return self._send(400, error_body("bad_image", "undecodable image"))

        acquired = SEM.acquire(timeout=15)
        if not acquired:
            return self._send(503, error_body("busy", "gateway concurrency %d full" % MAX_CONC, "rate_limit_error"))
        with STATS_LOCK:
            STATS["total"] += 1; STATS["in_flight"] += 1
        t0 = time.time()
        try:
            r = generate(model, prompt, image_bytes, extra)
            dt = round(time.time() - t0, 1)
            with STATS_LOCK:
                STATS["in_flight"] -= 1
                if r.get("status") == "success" and r.get("result_url"):
                    STATS["ok"] += 1
                    return self._send(200, {
                        "created": int(time.time()), "elapsed": dt,
                        "data": [{"url": r["result_url"], "revised_prompt": prompt}],
                        "upstream": {"runId": r["runId"], "status": r["status"]},
                    })
                STATS["err"] += 1
                return self._send(502, error_body("upstream_error",
                    "workflow %s / runId %s" % (r.get("status"), r.get("runId")), "api_error"))
        except Exception as e:
            with STATS_LOCK:
                STATS["in_flight"] -= 1; STATS["err"] += 1
            return self._send(502, error_body("upstream_error", str(e)[:300], "api_error"))
        finally:
            SEM.release()


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    srv.request_queue_size = 512
    print("pix-editor gateway on http://127.0.0.1:%d  models=%s conc=%d" % (PORT, sorted(MODEL_MAP), MAX_CONC))
    srv.serve_forever()


if __name__ == "__main__":
    main()
