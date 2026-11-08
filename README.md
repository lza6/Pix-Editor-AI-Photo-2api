# Pix Editor 2API

`com.snaptune.ai.photoeditor.collagemaker` v1.4.51 (PlatinumMods mod) 逆向 → OpenAI images 兼容网关。

**结论**：Apero 网关三条 AI workflow 全部端到端打通（i2i 图像编辑 ×2 + i2v 图生视频），无需模拟器、无需 Frida，纯协议复刻。

## 30 秒跑起来

```powershell
pip install cryptography pillow
python demo_server.py        # http://127.0.0.1:18733
# 浏览器打开 http://127.0.0.1:18733/demo
```

```powershell
# 压测（边界矩阵零成本；--allow-real 才打真实上游）
python stress_test.py --allow-real --conc 1 2 4 --rounds 2
```

可选环境变量：`PIX_PORT`（默认 18733）、`PIX_MAX_CONC`（默认 4）、`PIX_GATEWAY_KEY`（非空则要求 `Authorization: Bearer <key>`，`/health` 与 demo 页免鉴权）。

## 能力实测

| 模型 | 上游 workflow | 实测延迟 | 产物 | 证据 |
|---|---|---|---|---|
| `pix-editor-cheap` | 067b0760（qwen-editing 快速） | p50 13.5–18.4s | 848×848 JPEG（static.aperogroup.ai 直链） | 压测 20/20 + E2E 截图 |
| `pix-editor-expensive` | edb8925c（qwen-editing 精细） | ~90–120s | JPEG | round5c 实测 success |
| `pix-editor-i2v` | 3e28e0b0（图生视频） | ~120–180s | MP4（701KB 实测） | round5c + 下载验 md5 |

压测（2026-11-09，本机直连，conc×2 轮）：`conc=1: 2/2 ok p50=13.5s`，`conc=2: 4/4 ok p50=15.6s`，`conc=4: 8/8 ok p50=18.4s`，全程零 429 零失败；网关层并发闸门 4，超闸 503。

## API

OpenAI images 子集，JSON 与 multipart 双支持：

```
POST /v1/images/generations
{
  "model":  "pix-editor-cheap" | "pix-editor-expensive" | "pix-editor-i2v",
  "prompt": "turn the background into a cyberpunk city",
  "image":  "data:image/jpeg;base64,..." 或 "https://..." (可选, 留空用内置测试图),
  "video_model": "seedance-lite|seedance-pro|inhouse",   // 仅 i2v
  "background_prompt": "..."                             // 仅 i2v
}
→ 200 {"data":[{"url":"https://static.aperogroup.ai/...jpeg"}], "elapsed": 15.5, "upstream": {"runId": "..."}}
```

## 文件

| 文件 | 说明 |
|---|---|
| `core.py` | 协议实现：RSA 签名 → presigned → S3 PUT → workflow → 轮询 |
| `demo_server.py` | HTTP 网关 + demo 页路由 |
| `demo.html` | 演示页（选模型/prompt/传图，实时统计） |
| `stress_test.py` | 边界矩阵 + 并发阶梯 |
| `e2e_demo.py` | Playwright 真浏览器 E2E（零 console error 断言） |
| `docs/PROTOCOL.md` | 完整协议文档（含其它 5 条上游链路的探测结论） |
| `docs/NEW-API-INTEGRATION.md` | new-api 对接指南 |

## 限制

- 上游凭据（RC `api_key`）是厂商付费 key，被封/轮换需重拉 Firebase Remote Config（`docs/PROTOCOL.md` 有 3 步复拉法）。
- i2v 的 `video_model` 未逐一实测 `seedance-pro`/`inhouse`（只实测 `seedance-lite`），上游按 model 白名单校验（Kreivo 前科）。
- carve.photos（去背景）与 Klingai（虚拟试穿）需要各自的官方 API key，APK 内未提取到，未打通。
- RunPod 算力端点（`53f7hvxtjgzj4t`）`/run`、`/runsync` 均 404 —— pod 已摘除，该链路死。
