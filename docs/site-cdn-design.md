# 站点整站走 CDN 的仓库侧前置：Playground 端点的构建期 origin

> 状态：**current**。2026-10-02 落地仓库侧（生成器、play-ui、两个脚本）；CDN、源站 vhost、
> DNS 的切换不在本仓库，由部署侧按第五节的清单做。

## 一、问题

站点几乎全是静态页面，打算整域交给 CDN，HTML 与 `/assets/` 都从边缘出，源站只做回源。
挡路的只有 Playground：它在页面同源下用四个端点，`/api/run`、`/api/check`（POST）、
`/api/health`（GET），以及 `/api/lsp`（WebSocket 升级到 LSP 网关）。计划用的 CDN
不做 WebSocket 加速（厂商 FAQ 原话「暂不支持 websocket 加速」），而 WebSocket 在业界也普遍是
单独开关或单独产品，不是静态加速域名的默认能力。所以 `/api/lsp` 必须绕开 CDN。

只把 `/api/lsp` 拆出去不够干净：四个端点在源站是一组（同一套限流、同一台 runner、同一个
健康探测），拆一半等于源站要同时伺候两个 origin 的 `/api`。做法是四个一起搬到一个仍在
源站的独立 origin，页面留在 CDN 上。页面与 API 从此可能不同源，这就是本文的全部改动来由。

## 二、构建变量 `DAWN_SITE_PLAY_ORIGIN`

`site/build.sh` 导出它，默认空。生成器在 `site/src/main.dawn` 里读一次（`gen/pages.play_origin`，
与 `build_stamp`、首页数字同一条路：环境变量，不读文件，理由是 `scripts/site-dist-diff.sh`
在没有 `.git` 与 `selfhost/` 的快照里跑生成器，两条腿继承同一环境）。

- **空**：挂载点是 `<div id="dawn-playground" data-endpoint="/api/run"></div>`，与引入变量前
  逐字节相同。不设变量的构建产出的 `site/dist` 与改动前相同（第六节有证明）。
- **设置**：必须是裸 origin，`http(s)://` 加主机、可选端口，没有路径、没有尾斜杠，例如
  `https://play.example.test`。挂载点变成 `data-endpoint="<origin>/api/run"`。
- **不合法**：带路径、带尾斜杠、没有 scheme、或主机里出现字母数字与 `.-:` 以外的字符，
  构建直接 panic（`gen/pages.play_endpoint`）。字符集收窄也顺带保证这个值不需要转义就能
  进属性。

只有一个属性。前端从 run 的 URL 推出另外三个（第三节），生成器若写四个属性，四个就可能互相
不一致；一个属性不会。

链接检查（`gen/links`）不读 `data-endpoint`：`/api/run` 本来就不是生成器写出的文件，
绝对 URL 更不是站内链接。`gen/links.dawn` 里有一条测试把这件事钉住。

## 三、前端（`site/play-ui`）

`src/endpoints.ts` 的 `playEndpoints(run, location.href)` 把四个 URL 一次推好：
把末尾的 `/run` 换成 `/check`、`/health`、`/lsp`，再对页面地址解析成绝对 URL；LSP 那个
把 `http:` 换成 `ws:`、`https:` 换成 `wss:`（沿用 `lsp.ts` 的 `lspWebSocketUrl`）。
所以相对端点时三个兄弟落在页面 origin，绝对端点时全部落在 API 的 origin，任何地方都不
拿 `location.origin` 去拼。

挂载点没有 `data-endpoint` 时直接抛错，bundle 里不再留 `/api/run` 这个默认值：端点是页面
说了算，bundle 里的第二份默认值只会在某天与生成器分叉。不以 `/run` 结尾的端点同样抛错
（以前是静默不替换，check 会打到 run 上）。

跨域请求不用改写法：`fetch` 默认 `mode: 'cors'`、`credentials: 'same-origin'`，跨域时不带
cookie，也不需要带。`POST` 带 `Content-Type: application/json`，不是 CORS 的简单请求，浏览器
会先发 `OPTIONS` 预检。`GET /api/health` 是简单请求，不预检，但响应同样要带
`Access-Control-Allow-Origin`，否则版本号读不到（页面照常可用，只是工具栏不显示版本）。
WebSocket 不受 CORS 约束，浏览器自动带页面的 `Origin`，网关逐字核对 `PLAY_LSP_ORIGINS`
的逻辑不用改：页面 origin 仍是站点地址，没有变。

bundle 增量：`playground.js` 原始 +262 B，gzip -9 +91 B（143,680 → 143,771 B）。

## 四、脚本

- `scripts/play-live-check.py`：新增 `PLAY_API_URL`（`/api` 的基址，不含 `/run`）。不设时等于
  `PLAY_BASE_URL` 加 `/api`，即同源部署，行为不变；设了以后 runner 检查打到 API 的 origin，
  静态页检查仍在 `PLAY_BASE_URL`。
- `playground/deploy/redeploy.sh`：末尾提示的健康 URL 读 `PLAY_HEALTH_URL`，默认仍是
  `https://dawn-lang.dawnop.com/api/health`。

两个默认值都不在本次改动里变；切换那天由部署侧设置变量或改默认值。

## 五、源站要满足的契约

本节只写仓库代码依赖的行为，不写具体的 vhost、域名、证书与地址，那些在私有部署仓库。

1. API origin 承接 `/api/run`、`/api/check`、`/api/health`、`/api/lsp` 四个路径，映射与今天
   站点 vhost 下的 `/api/` 相同（runner 的 `/run`、`/check`、`/health`，网关的 WebSocket）。
   限流照搬。
2. `run`、`check`、`health` 的响应带 `Access-Control-Allow-Origin: https://dawn-lang.dawnop.com`
   （逐字，不用 `*`；有 `Vary: Origin` 更稳）。429、413 等错误响应也要带，否则前端读不到
   状态码，只会看到网络错误（nginx 的 `add_header` 要加 `always`）。
3. `OPTIONS` 预检回 204，带 `Access-Control-Allow-Origin`（同上）、
   `Access-Control-Allow-Methods: POST, GET, OPTIONS`、`Access-Control-Allow-Headers: Content-Type`，
   可加 `Access-Control-Max-Age` 减少预检次数。不需要 `Allow-Credentials`。
4. `/api/lsp` 不加 CORS 头，网关的 Origin 白名单保持站点地址。
5. 站点 vhost 变成 CDN 的回源块后不再有 `/api/`。

构建时以 `DAWN_SITE_PLAY_ORIGIN=<API origin> ./site/build.sh` 出产物，再部署。顺序上先让
API origin 上线并通过 `PLAY_API_URL=<API origin>/api scripts/play-live-check.py`，再发布带绝对
端点的页面，最后切 DNS；回滚时页面用空变量重建即可回到同源。

## 六、验证（2026-10-02）

- 生成器差分：`origin/main` 的生成器与本次的生成器，在同一份快照数据、同一个 bundle、
  变量为空时写出的 `site/dist` 逐字节相同（`diff -r` 无输出）。设为 `https://play.example.test`
  时只有 `playground.html` 与 `zh/playground.html` 的挂载点一行不同，链接检查照常通过。
- 尾斜杠的 origin 让构建以 `not an origin` 失败；把校验改成恒真的变异体让
  `a play origin makes the endpoint absolute` 变红。
- 浏览器端：两种产物各在本机伺服，向本机 runner 发 Run 都拿到输出；绝对端点下 run、check、
  health 的请求与 LSP 的 WebSocket 都发往 API 的 origin（本机用一个带 CORS 头的小代理模拟
  第五节的源站行为），run 与 check 各先有一次 `OPTIONS` 预检。负控：同一代理去掉 CORS 头，
  Run 报 `Could not reach the run service`，控制台是三条 CORS 拦截，第五节的头确实是必需的。
- `PLAY_BASE_URL` 指本机静态站、`PLAY_API_URL` 指本机 CORS 代理跑 `play-live-check.py`：
  24 项全过，runner 的请求全部落在代理上。
- `scripts/site-dist-diff.sh` 在变量为空与设置两种环境下各跑一次，JVM 与 native 的 158 个
  产物均逐字节相同。

## 七、不做的（理由）

- **不把 API 的域名写进仓库。** 默认值保持现状，新 origin 只在构建与部署时以变量给出；
  仓库里除站点公开地址外不出现任何部署域名、IP 或登录名，部署细节归私有部署仓库。
- **不给 check、health、lsp 各开一个属性。** 理由见第二节，一个属性不会自相矛盾。
- **不在前端加运行期的 origin 配置**（例如读 `<meta>` 或全局变量）。端点是构建产物的一部分，
  `site-dist-diff` 两条腿看到的是同一个值；运行期配置会让同一份 dist 在不同地方行为不同。
- **不让 CDN 代理 `/api/run` 与 `/api/check`。** CDN 支持 POST 回源，但 `/api/lsp` 反正要走
  另一个 origin，同一组端点分两处会让限流、健康探测与回滚各多一种情形。
- **不改网关的 Origin 校验。** 页面 origin 没变，白名单不需要变。
