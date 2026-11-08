# Pix Editor 协议文档

APK：`Pix_Editor_AI_Photo_Maker_v1.4.51_modded_by_PlatinumMods.apk`
包名：`com.snaptune.ai.photoeditor.collagemaker`（versionCode 55）
Mod 重签证书 SHA1：`ae846c58d56c0eceb2eb0c1d4ccbcfd11ab53672`（上游不校验签名，mod 包可直接用）

## 结论速览（证据等级）

| 结论 | 证据等级 |
|---|---|
| 三条 workflow（cheap/expensive/i2v）端到端出产物 | **已验证**（真机协议实测，JPEG 848² / MP4 701KB） |
| Apero 网关 RSA 签名 = `b64(RSA-PKCS1v15("ts@@@apiKey@@@rand0..999999"))` | **已验证**（签名错→412/401，签名对→200） |
| RC `api_key`（sk-…，已打码）是网关凭据，RC 自愈可重拉 | **已验证**（拉取 160 entries） |
| 上传链：presigned-link → S3 PUT（`Content-Type: image/jpg` 必须逐字匹配）→ **裸 path**（`data.path`，不能加 `s3://`） | **已验证**（PUT 200 vs 404 对照） |
| workflow 状态枚举是 `queued/running/success/failed`（**不是** `completed`） | **已验证** |
| Terafort（pix-editor-backend.aspire.pics）设备即身份、零验证注册发 token | **已验证**（201 + access_token） |
| GraphQL asset API（v2.framme.online）凭据 `snapeditor`/`se@assetapi` 硬编码，发 5min JWT | **已验证** |
| Xilli 资产 API 硬编码 Bearer 可用 | **已验证**（登录链路 200） |
| RunPod 算力端点 `53f7hvxtjgzj4t` 已死 | **已验证**（/run、/runsync 均 404 endpoint not found） |
| carve.photos / Klingai 需官方 key，未提取 | 静态确认（接口签名可见，key 未定位） |
| Terafort 积分系统不参与网关执行门禁 | 合理推断（0 积分设备连发 20+ 次全部成功） |

## 1. Apero 网关签名链

```
1. GET {base}/timestamp → {"data":{"timestamp":<ms>}}
2. payload = "{ts_ms}@@@{api_key}@@@{random(0,999999)}"
3. signature = base64( RSA/ECB/PKCS1Padding(pubkey, payload) )
4. 8 个头:
   app-name: x
   x-api-token: not_get_api_token      ← Play Integrity 占位，服务端不校验
   x-api-signature: <signature>
   x-api-timestamp: <ts_ms>
   x-api-bundleid: com.snaptune.ai.photoeditor.collagemaker
   x-api-keyid: 1
   country-code: US
   app-version: 1.4.51
```

- RSA 公钥硬编码在 `core/utils/AperoSignatureUtil.java`（`PUBLIC_KEY_PEM`），与 Glovy/Fravix/Kreivo/Alura 全族共用同一公钥。
- **边缘 WAF**：无 8 头时一律 `412 Precondition Failed`（`{"error":"Precondition Failed"}`）；占位值 `x` 即可过边缘，真实校验在应用层。
- api_key 来源：Firebase Remote Config 的 `api_key`。RC 拉取（Kreivo 路线，无需设备）：

```
POST https://firebaseremoteconfig.googleapis.com/v1/projects/apl789-snap-tune-ai/namespaces/firebase:fetch?key=AIza<公开 client key, 从 resources.arsc 提取>
Headers: X-Android-Package: <包名>, X-Android-Cert: <证书SHA1>, Content-Type: application/json
Body: {"app_instance_id":"<32hex随机>","app_id":"1:403164139289:android:13f9dff35ce63cf543bf88",
       "platform_version":"30","package_name":"<包名>","app_version":"1.4.51",
       "language_code":"en","time_zone":"UTC","country_code":"US"}
→ entries: 160 条 (templateVersion 1202)，其中 api_key / workflow_id_* / demo_* 全部下发明文
```

## 2. 端点矩阵（Apero 网关 api-img-gen-wrapper.apero.vn）

| 方法 | 路径 | 说明 | 实测 |
|---|---|---|---|
| GET | `/timestamp` | 服务器时间（ms） | 200 |
| GET | `/health` | `{"details":[{"wrapper":{"limit":20}}]}` | 200 |
| GET | `/api/v5.1/qwen-editing/presigned-link` | 返回 `data.url`（S3 presigned PUT，120s）+ `data.path`（裸 key） | 200 |
| PUT | `data.url` | 上传图片，`Content-Type` 必须 = 签名内的（`image/jpg`） | 200 |
| POST | `/api/v1/workflow/execute` | `{"workflowId":"...","input":{...}}` → 201 `{"runId","status":"queued"}` | 201 |
| GET | `/api/v1/workflow/execute/{runId}` | 轮询；`status ∈ queued/running/success/failed` | 200 |
| POST | `/api/v5.1/qwen-editing` | 直连 qwen（网关内部节点也走它），`{"files":[path],"prompt"}` | 400 无真实图时（节点层自证）|

## 3. 三条 workflow 的输入 schema（jadx 静态 + 实测校验）

| 模型名 | workflowId | input 字段 |
|---|---|---|
| cheap | `067b0760-58e1-4033-addf-2ebb26498ed3` | `{files: [bare_path], prompt}` |
| expensive | `edb8925c-f39c-4c43-b41d-7917b2efe19b` | `{files: [bare_path], prompt}` |
| i2v | `3e28e0b0-9233-45ca-85fb-c01691080106` | `{files: [bare_path], mode: "i2v", model: "seedance-lite\|seedance-pro\|inhouse", positivePrompt, backgroundPrompt}` |

- 内部节点结构（轮询响应 `nodes[]` 可见）：cheap/expensive 是 `request_inputs → request_inputs__safety → art/qwen_editing → response`；i2v 是 `request_inputs → safety → qwen_editing → video_inhouse → response`。
- **`art` 节点报 `File must be a string` 属误导**——那是 DNS 上游错误，真正的坑是路径格式：必须用 `data.path` 的裸值（`ai-core-qwen-editing/20261108/xxx/input.jpg`），加 `s3://` 前缀或任何 URL 包装都会让 safety 节点 `Unable to decode the provided image file`。

## 4. 响应字段

```json
// 轮询 (success, cheap)
{"runId":"...","status":"success","input":{...},
 "output":{"resultFile":"https://static.aperogroup.ai/ai-core-qwen-editing/.../output/xxx_0.jpeg","resultStatus":"completed"},
 "nodes":[...]}
// cheap/expensive: output.resultFile 是字符串 URL
// expensive: response 节点 resultFile 可能是数组 (取 [0])
// i2v: output.resultFile = ...output.mp4; nodes[video_inhouse].meta.payload.videoId 可追踪
```

CDN 直链：`static.aperogroup.ai/...`，无鉴权可 GET（实测下载 JPEG/MP4 成功，md5 校验通过）。

## 5. 其它上游链路（同 APK 内的旁路）

### 5.1 GraphQL asset API（模板/贴纸目录）
- `POST https://v2.framme.online/api`，`mutation AuthenticateApp($username,$password){authenticateApp{token}}`
- 凭据硬编码 `core/common/Constants.java`：`AUTH_USERNAME="snapeditor"`，`AUTH_PASS="se@assetapi"`
- 发 HS256 JWT（约 5min TTL，载荷 `{username, exp, origIat}`）。demo 账号 `pixtest@tf.com` 在 RC 里但密码已轮换，用上面的硬编码凭据即可。

### 5.2 Terafort 积分后端（pix-editor-backend.aspire.pics）
- `POST /api/register_device/`，头 `X-Device-ID: <32hex 任意>` → 201 直发 `access_token` + `refresh_token`（设备即身份，零验证）。
- `GET /api/coins/balance/`（头 `Device-Id` + `Authorization: Bearer <access_token>`）、`GET /api/plansList/`、`POST /api/coins/claim|deduct/`、`POST /api/plans/consume/`、pixverse 视频队列系列。
- **积分系统不参与本次三条 workflow 的执行门禁**：0 积分新设备连发 20+ 次全成功（客户端侧积分墙，服务端未强制）。

### 5.3 Xilli 资产 API（api.xilliapps.com）
- `POST api/getFrameHeader|getFrameBody|getCategoriesAndFrames|getStickerHeader|getStickerBody`，multipart，**硬编码** `Authorization: Bearer 21|<已打码, 从 RetrofitServiceInterfaceXilli.java 注解提取>`（`RetrofitServiceInterfaceXilli.java` 注解）。

### 5.4 RunPod（api.runpod.ai/v2/53f7hvxtjgzj4t）
- 硬编码 `Authorization: Bearer <已打码, RunPod 端点已死, 无复用价值>`；实测 `/run`、`/runsync` 均 `404 {"detail":"endpoint not found"}` → pod 已摘除，链路死亡。

### 5.5 carve.photos（去背景）
- `GET api/v1/images/images/{id}` / multipart remove，头 `X-API-Key` 必填（无 key → 403 `{"detail":"Not authenticated"}`）；key 在 ViewModel 参数链中未定位（jadx 参数名混淆），未打通。

### 5.6 Klingai 虚拟试穿
- `POST https://api.klingai.com/v1/images/kolors-virtual-try-on`，`Authorization` 由上游签发（APK 里是空字符串占位），无 key → 401 `Authorization is empty`。上游是官方 API，需用户自有 key。

## 6. 踩坑表（现象 | 真实原因 | 修法）

| 现象 | 真实原因 | 修法 |
|---|---|---|
| 全部 412 Precondition Failed | 边缘 WAF 要求 8 头齐全 | 头值占位 `x` 也能过边缘 |
| workflow 201 但轮询 `failed` / `Unable to decode image` | files 传了 `s3://` 前缀或 URL | 用 presigned 响应的 `data.path` **裸值** |
| 轮询永远拿不到终态 | 状态枚举是 `success` 不是 `completed` | 判 `in (success, failed)` |
| PUT 403 SignatureDoesNotMatch | Content-Type 与 presigned URL 内 `Content-Type=image%2Fjpg` 不一致 | PUT 时 `Content-Type: image/jpg` 逐字匹配 |
| 400 `Files must be an array`（POST 后） | 请求体没带 `Content-Type: application/json`（urllib 默认 form） | 显式 JSON CT |
| qwen-editing 400 `Unable to decode` | 上传的是 1×1 PNG 但 URL 签的是 image/jpg | 传真实 JPEG |
| 网关请求秒断 RemoteDisconnected | Python 3.14 `threading.Semaphore` 无 `.locked()`，异常在 try 外 | 不检查 `.locked()` |
| workflow/execute ERR100 `workflowId should not be empty` | JSON 体未被解析（CT 缺失） | 显式 `application/json` |

## 7. 风控与额度

- 网关侧：免费额度由客户端 Terafort 计费墙控制（`coins/balance` 初始 0，`claim` 看广告/`daily_reward` 领币）；服务端未对 workflow 执行做积分校验——0 余额设备连发 20+ 次全部成功。
- 未见 IP 级限流（本机单线程 20 次 + 4 并发 8 次，零 429）。
- workflow `wrapper.limit=20`（/health 自述），生产建议网关并发 ≤4。
- Play Integrity（`x-api-token`）不校验：传 `not_get_api_token` 直接过。
- 上游会做内容 safety 检查（`request_inputs__safety` 节点），NSFW/违规图会 fail；prompt 层面未见审核。

## 8. 混淆情况

- 原生 Kotlin + Retrofit/OkHttp + Apollo GraphQL + Hilt，`libpglarmor.so`（AppSealing 壳）与 `libsigner.so` 存在但不影响网络层（业务明文 HTTP，cert pinning 未开启）。
- jadx 对部分 Kotlin 协程类名做了 `n`/`C05581` 混淆重命名，参数名不可信——以 DTO 字段与实测为准。