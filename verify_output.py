import os, sys, hashlib, urllib.request, ssl, json
sys.stdout.reconfigure(encoding='utf-8')
CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
url = "https://static.aperogroup.ai/ai-core-qwen-editing/20261108/8d8931c9-ba64-4488-8ebf-38c6243c6943/output/1794178777012_0.jpeg"
r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "okhttp/4.9.3"}), context=CTX, timeout=30)
raw = r.read()
open(os.path.join(os.path.dirname(__file__), "evidence_gateway.jpeg"), "wb").write(raw)
from PIL import Image
import io
im = Image.open(io.BytesIO(raw))
print(f"gateway real output: {len(raw)}B md5={hashlib.md5(raw).hexdigest()[:12]} {im.size} {im.format}")
