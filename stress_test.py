# -*- coding: utf-8 -*-
"""Pix Editor 2API 压测: 并发阶梯 + 边界矩阵 (默认只打 mock-free 网关真实链路, 需 --allow-real)"""
import json, sys, time, threading, urllib.request, urllib.error, ssl, argparse, statistics

sys.stdout.reconfigure(encoding='utf-8')
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
BASE = "http://127.0.0.1:18733"

def req(method, path, body=None, timeout=330):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method=method)
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(r, timeout=timeout, context=CTX)
        return resp.status, resp.read().decode(), round(time.time() - t0, 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), round(time.time() - t0, 1)
    except Exception as e:
        return -1, f"{type(e).__name__}", round(time.time() - t0, 1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-real", action="store_true", help="跑真实生成 (每次消耗上游)")
    ap.add_argument("--conc", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args()

    st, b, _ = req("GET", "/health")
    print(f"[health] {st} {b[:180]}")
    if st != 200:
        sys.exit(1)

    # ---- 边界矩阵 (零成本) ----
    print("\n===== edge matrix =====")
    edges = [
        ("no-prompt", {"model": "pix-editor-cheap"}),
        ("list-body", None),  # 特判: 发数组
        ("bad-model", {"prompt": "x", "model": "gpt-4"}),
        ("empty-obj", {}),
    ]
    for name, body in edges:
        if body is None:
            r = urllib.request.Request(BASE + "/v1/images/generations", data=b"[1,2,3]",
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                resp = urllib.request.urlopen(r, timeout=20, context=CTX)
                print(f"  {name}: {resp.status}")
            except urllib.error.HTTPError as e:
                print(f"  {name}: {e.code} {e.read().decode()[:100]}")
            except Exception as e:
                print(f"  {name}: ERR {type(e).__name__}")
        else:
            st, b, _ = req("POST", "/v1/images/generations", body)
            print(f"  {name}: {st} {b[:110]}")

    if not a.allow_real:
        print("\n(skip real load test: pass --allow-real)")
        return

    # ---- 并发阶梯 (真实) ----
    print("\n===== real load test =====")
    for conc in a.conc:
        lat, ok, err = [], 0, 0
        t0 = time.time()
        def worker(i):
            nonlocal ok, err
            st, b, dt = req("POST", "/v1/images/generations",
                {"prompt": f"stress test {conc}x: turn the sky purple #{i}", "model": "pix-editor-cheap"})
            if st == 200 and '"url"' in b:
                ok += 1; lat.append(dt)
            else:
                err += 1
                print(f"    worker{i}: {st} {b[:80]}")
        ths = [threading.Thread(target=worker, args=(i,)) for i in range(conc * a.rounds)]
        # 分轮启动: 每轮 conc 个并发
        for rnd in range(a.rounds):
            batch = ths[rnd * conc:(rnd + 1) * conc]
            for t in batch: t.start()
            for t in batch: t.join()
        wall = round(time.time() - t0, 1)
        n = conc * a.rounds
        rps = round(n / wall, 2)
        if lat:
            lat.sort()
            p50 = statistics.median(lat)
            p95 = lat[int(len(lat) * 0.95) - 1] if len(lat) > 1 else lat[0]
        else:
            p50 = p95 = -1
        print(f"  conc={conc}: {ok}/{n} ok, wall={wall}s, rps={rps}, p50={p50}s, p95={p95}s")
    st, b, _ = req("GET", "/health")
    print(f"[final stats] {b[:250]}")

if __name__ == "__main__":
    main()
