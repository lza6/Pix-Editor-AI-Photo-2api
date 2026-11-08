# PixEditor-2api 对接会话启动 Prompt

> 把本文件全文粘贴给新会话即可开工。无需其它上下文。

---

## 任务

把 GitHub 仓库 `https://github.com/lza6/Pix-Editor-AI-Photo-2api`（已克隆或现场 clone）交付的 Pix Editor 2API 网关，对接到生产 new-api 实例。new-api 侧操作由你执行；对接方式用**路线 A（零代码 OpenAI 兼容渠道）**，路线 B（原生 Go 渠道）已评估为不必要，不要做。

## 第一步（必做）

读完仓库里的 `docs/NEW-API-INTEGRATION.md`（对接契约）与 `README.md`（能力实测表），然后逐项执行其「验收清单」。

## 硬约束（违反即返工）

1. **Base URL 不带 `/v1`**：填 `http://<host>:18733`。new-api 的 OpenAI 渠道会自动拼 `/v1/images/generations`；带 `/v1` 会变成 `/v1/v1/...` 404。
2. **渠道「测试」按钮必失败**：它打的是 `/v1/chat/completions`，本网关是纯图像服务。验收必须用生图 curl（文档里有现成命令），不要因为测试按钮红叉就判定渠道坏了。
3. **模型倍率必须先配**：`pix-editor-cheap/expensive/i2v` 不在 new-api 内置倍率表，不配就按兜底 **37.5** 计费（是 gpt-image-1 的 15 倍）。按张计费分别设置。
4. **客户端必须传 `image`**：三个模型都是图生图/图生视频，上游没有纯文生图。不传 image 时网关用内置测试图出图——演示可以，生产渠道描述里必须写明，否则用户投诉"生成的图跟 prompt 无关"。
5. **超时**：cheap ≥60s、expensive ≥180s、i2v ≥300s（new-api 渠道超时字段与客户端都要设）。
6. **i2v 返回 mp4 URL**：OpenAI images 语义是图，客户端按返回 `url` 后缀判断类型；`b64_json` 恒为空。
7. **凭证纪律**：网关上游 key 通过 `PIX_APERO_API_KEY` 环境变量注入（仓库里的默认值是占位符）；不要把任何真实 key 写进 new-api 数据库备注、commit 或文档。

## 网关侧部署

```powershell
git clone https://github.com/lza6/Pix-Editor-AI-Photo-2api
cd Pix-Editor-AI-Photo-2api
pip install cryptography pillow
$env:PIX_APERO_API_KEY="<向仓库维护者索要或从 Firebase RC 重拉>"
$env:PIX_GATEWAY_KEY="<自选一个随机串, 作为 new-api 渠道密钥>"
python demo_server.py   # 监听 127.0.0.1:18733
```

生产部署建议用计划任务/nssm 注册为服务；`PIX_MAX_CONC` 默认 4，不要调大（上游 /health 自述 wrapper.limit=20，留余量给其它消费者）。

## 验收命令（对接完成后逐条跑）

```bash
# 1. 网关健康
curl http://127.0.0.1:18733/health
# 2. 经 new-api 的真实生图（把 <new-api> 与 <sk> 换成生产值）
curl http://<new-api>/v1/images/generations -H "Authorization: Bearer <sk>" \
  -H "Content-Type: application/json" \
  -d '{"model":"pix-editor-cheap","prompt":"turn the sky purple","image":"data:image/jpeg;base64,/9j/4AAQSkZJRg...","n":1}'
# 3. i2v（可选, ~150s）
# model 换 pix-editor-i2v, 返回 url 以 .mp4 结尾即 PASS
```

PASS 标准：200 + `data[0].url` 指向 `static.aperogroup.ai` 且 URL 可下载打开。

## 故障速查

| 症状 | 处置 |
|---|---|
| 网关 502 且日志含 401/ERR15 | 上游 key 失效：按仓库 `docs/PROTOCOL.md` §1 重拉 Firebase RC 换 `PIX_APERO_API_KEY` |
| 503 busy | 并发闸门满，属预期背压；检查是否有调用方并发超 4 |
| 全部请求 502 `upstream_error` | 先 `curl https://api-img-gen-wrapper.apero.vn/health`（带 8 头）判上游死活，别急着改网关 |
| new-api 侧 404 | 检查 Base URL 是否误带 `/v1` |
