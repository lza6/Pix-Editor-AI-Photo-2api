# Pix Editor 2API → new-api 对接指南

自包含任务契约：任何没有上下文的会话/人可直接执行。

## 事实速查（5 条）

1. 网关默认监听 `127.0.0.1:18733`，OpenAI images 子集：`POST /v1/images/generations`（JSON 或 multipart 均可）。
2. 三个模型名：`pix-editor-cheap`（~15s）、`pix-editor-expensive`（~90s）、`pix-editor-i2v`（~150s，返回 mp4 URL）。
3. 所有生成都必须有图（i2i/i2v 上游没有纯文生图）；不传 `image` 时网关切内置 512² 测试图（仅演示用）。
4. 响应是 `{"data":[{"url":"https://static.aperogroup.ai/..."}]}`，CDN 直链公开可下载。
5. 并发闸门默认 4（`PIX_MAX_CONC`），超闸返回 503；上游健康时 p50 13.5–18.4s。

## 路线 A：零代码 —— OpenAI 兼容渠道（推荐）

new-api 后台 → 渠道 → 新增：

| 字段 | 值 |
|---|---|
| 类型 | OpenAI |
| Base URL | `http://<网关主机>:18733`（**不要带 `/v1`**，new-api 会拼 `/v1/images/generations`） |
| 密钥 | 网关了 `PIX_GATEWAY_KEY` 时填它；否则填任意非空串 |
| 模型 | `pix-editor-cheap,pix-editor-expensive,pix-editor-i2v` |

注意：

- **「测试」按钮打 `/v1/chat/completions` 必失败**——本网关是纯图像服务，属预期；用下面的 curl 验证渠道。
- 客户端调用：

```bash
curl http://<new-api>/v1/images/generations -H "Authorization: Bearer sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{"model":"pix-editor-cheap","prompt":"turn the sky purple","image":"data:image/jpeg;base64,<b64>","n":1}'
```

- 模型倍率：这三个名字不在 new-api 内置 `ModelRatio` 表，未手工配置会按兜底 **37.5** 计费（= gpt-image-1 的 15 倍）。上线前必须在「倍率设置」里给三个模型配好（建议按张计费，cheap/expensive/i2v 分别设）。

## 路线 B：原生 Go 渠道（仅当需要流式/自定义语义时）

不建议：本网关就是 OpenAI images 语义，路线 A 足够。若确需原生渠道，改动清单：

1. `constant/channel.go`：新增 `ChannelTypePixEditor`
2. `constant/api_type.go`：iota 顺序追加 + `common/api_type.go` 的 `ChannelType2APIType` 映射
3. `relay/adaptor/`：新建适配器实现 `relay.Adaptor`（`GetRequestURL` = baseURL + `/v1/images/generations`，`DoRequest` 直接转发，无需签名——签名在网关内完成）
4. `relay/adaptor.go` 的 `GetAdaptor`、前端 `web/src/features/channels/constants.ts` 两处同步
5. 计费：`relay/image_handler.go` 的 `PostTextConsumeQuota` 路径不变

## 上游故障/换密钥的恢复动作（给维护者）

凭据失效（网关 502 且日志含 `401`/`ERR15`）时：

1. 重拉 Firebase RC（命令见 `docs/PROTOCOL.md` §1 的 3 步），取新 `api_key` 替换 `core.py` 的 `API_KEY`。
2. workflow UUID 变了查 RC 的 `workflow_id_i2i_cheap/expensive/i2v` 三个键。
3. 网关重启：`PIX_PORT=18733 python demo_server.py`。

## 验收清单

- [ ] `curl :18733/health` → `{"ok":true,...}`
- [ ] `curl :18733/v1/models` → 3 个模型
- [ ] new-api 渠道用上面的 curl 真实出图（200 + static.aperogroup.ai URL）
- [ ] 浏览器打开 `:18733/demo` → 选模型→生成→出图，控制台零 error
- [ ] 倍率已配（不然 37.5 倍兜底）

## 已知坑（对接时最容易踩）

| 坑 | 规避 |
|---|---|
| Base URL 带 `/v1` | 只填 `http://host:port` |
| 渠道测试按钮报错 | 预期行为，用生图 curl 验收 |
| 无 image 参数 | 网关会出「内置测试图改背景」——演示可以，生产调用方必须自己的图 |
| i2v 返回 mp4 但 OpenAI images 语义是图 | 客户端按 `url` 后缀自行判断；不要指望 `b64_json` |
| 超时 | 给 cheap≥60s、expensive≥180s、i2v≥300s |