# Lightweight Status Monitor

Python worker 采集 HTTP 服务、Node Exporter 与 Prometheus 指标，SQLite 保存历史；React 展示当前状态和预聚合历史。API 只读取私有快照，不在浏览器读取数据时查询完整历史。

## 配置与目录

```text
configs/
    general.json
    resources/
        default.json
    .env
configs-pusr/            # 独立实例的私有目录，不跟踪
    general.json
    resources/
    .env
data/                    # 数据库、会话、调度状态和私有快照，不跟踪
```

首次安装时复制 `configs/general.example.json` 为 `configs/general.json`，复制 `configs/resources/example.json.example` 为 `configs/resources/default.json`。真实配置和秘密不提交到 Git。

`general.json` 的 `resource_dirs` 为目录数组，默认 `["configs/resources"]`，支持绝对路径；所有相对路径统一相对 status 仓库根目录。目录内加载 `.json` 文件，文件只是组织方式，集群归属由资源的 `cluster` 字段或 Prometheus 标签决定。同一资源不能在多个文件重复定义。

```json
{
  "database": "data/status.db",
  "status_json": "data/snapshots/current.json",
  "resource_dirs": ["configs/resources", "/srv/shared/status-resources"],
  "service_interval_seconds": 600,
  "failure_threshold": 3,
  "request_timeout_seconds": 8,
  "history_hours": 1440,
  "refresh": {
    "minimum_seconds": 10,
    "idle_seconds": 300,
    "lease_seconds": 75,
    "presets": [10, 20, 60]
  },
  "auth": {
    "shizunet": { "enabled": false },
    "pseudo_user": { "enabled": false }
  }
}
```

resource 示例：

```json
{
  "services": [
    { "id": "home", "name": "Home", "url": "https://example.com", "cluster": "Public", "order": 0 }
  ],
  "servers": [
    { "id": "app", "name": "App", "target": "100.64.0.10:9100", "cluster": "Internal", "order": 0 }
  ]
}
```

`id` 建议显式指定，改名或移动文件不会改变身份。省略时从端点生成稳定 ID。`order` 决定配置排序，同值保持加载顺序。机器 target 可以直接写 `100.x.x.x:9100`。可在资源文件设置 `prometheus` 对象或对象数组，与静态机器并存：

```json
{
  "prometheus": {
    "url": "http://prometheus:9090",
    "job": "nodes",
    "enabled_label": "status_enabled",
    "enabled_value": "true",
    "name_label": "status_name",
    "cluster_label": "cluster"
  }
}
```

每份 general 加载其同目录的 `.env`，进程环境变量优先。general 和 resource 字符串均支持 `${VARIABLE}`，缺失变量会阻止启动；不会执行 shell 表达式，也不会把一个实例的环境注入另一个实例。`STATUS_DATABASE`、`STATUS_JSON` 可覆盖对应路径。配置在进程启动时读取，修改后重启对应 worker 和 API。

## 账号与公开访问

Shizunet 或本地备用账号任一启用时，匿名用户仅可读取 Services History；两种登录均关闭时完整页面可用。关闭 Shizunet、仅启用 pseudo user 即为本地账号登录模式。机器、服务当前状态、机器历史及 `/check` 均要求 status 登录。已有 status 会话不依赖身份提供方在线；Shizunet 故障不会自动关闭鉴权。

启用 Shizunet：

```json
{
  "auth": {
    "shizunet": {
      "enabled": true,
      "issuer": "https://auth.example.com",
      "client_id": "status",
      "client_secret": "${STATUS_OIDC_SECRET}",
      "base_url": "https://status.example.com"
    },
    "pseudo_user": {
      "enabled": true,
      "username": "${STATUS_PSEUDO_USERNAME}",
      "password_hash": "${STATUS_PSEUDO_PASSWORD_HASH}"
    }
  }
}
```

在 `configs/.env` 设置上述变量并限制文件权限为 `600`。Shizunet 私有环境中设置同一密钥 `OIDC_STATUS_SECRET` 和 `STATUS_URL`，重启 Shizunet；回调为 `${STATUS_URL}/auth/callback`。status 使用独立 OIDC 客户端、PKCE、nonce 和服务端会话，不保存 Shizunet 密码。

pseudo user 为独立本地备用身份，不走 Shizunet。生成密码哈希：

```bash
.venv/bin/python -m backend.status_monitor.auth
```

将输出填入 `STATUS_PSEUDO_PASSWORD_HASH`。生产启用 HTTPS 时 Cookie 自动使用 Secure。若只启用本地账号，可设置 `auth.base_url` 明确部署地址。Account 提供两种登录入口；当前不做集群授权和跨设备设置同步。

## 刷新与快照

- 顶部保留三个周期按钮（默认 10/20/60 秒）及刷新按钮。Control 修改三个按钮的数值，设置保存在本机浏览器；general 的 presets 提供初始值。
- 活跃页面每 20 秒续租。机器采集周期取所有活跃页面请求周期的最小值，并受服务器 `minimum_seconds` 下限约束；没有活跃页面时使用 `idle_seconds`。
- 活跃页面可以请求比静息周期更长的间隔。低于下限时客户端提示下限，不提示其他页面造成的更高采集频率。
- 新连接和手动刷新请求尽早采集，多请求合并；采集不重叠，两次开始时间至少相隔最小间隔，失败也占用这次机会。
- 页面隐藏后停止续租，异常断开通过租约到期回归静息周期；心跳与数据读取周期独立。关闭自动刷新会释放租约，仍可手动刷新。
- 服务探测保留独立周期，手动刷新 Services 可以请求提前探测，同样受最小间隔约束。
- GET `/status?probe=...` 不再触发采集。控制接口为同源 POST，受权限、速率和页面数量限制。

worker 采集完成后增量更新按小时/天聚合的历史，并原子生成私有快照。API 在文件版本变化时重新加载，不反复执行历史查询。当前状态、48 小时历史和 60 天历史分别传输；已有快照在进程重启后可直接使用。快照必须位于静态目录之外，旧 `/status.json` 降级路径不再提供。

首次加载显示加载状态，后台更新保留现有数据，失败保留旧数据并提示。服务历史全成功为绿色、全失败为红色、混合为黄色、没有数据为灰色。历史展示为 48 小时/60 天；当前不会自动删除原始采集数据，聚合窗口保留 61 天。

Filter 控制集群及机器可见性，Display 控制排序、列表/网格、宽度与每行卡片上限。样式沿用 status 的圆角、透明背景和分段按钮。网络指标保存为 bytes/minute、页面换算为 bytes/s；Node Exporter counter 需要两次样本才能计算速率，Prometheus 使用 `rate()`。

## 运行与部署

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install
npm run build
pm2 startOrRestart ecosystem.config.cjs --update-env
pm2 save
```

PM2 使用本仓库 `.venv/bin/python`，避免继承其他项目环境：

- `status-worker` / `status-api`：`configs/general.json`，API `127.0.0.1:18080`。
- `status-pusr-worker` / `status-pusr-api`：`configs-pusr/general.json`，API `0.0.0.0:18081`，保留现有内网访问方式。

两个实例分别指定数据库和快照目录；会话与控制数据库从业务数据库路径派生，相互隔离。每个实例只允许一个 worker，文件锁防止重复启动。

本地运行：

```bash
.venv/bin/python -m backend.status_monitor.worker --config configs/general.json
.venv/bin/python -m backend.status_monitor.api --config configs/general.json --static-dir dist
```

API：`GET /api/session`、`GET /status`、`GET /history/services?range=60d`、`GET /history/servers?range=48h`、`GET /check`、`GET /healthz`。历史仅支持固定窗口；匿名可读服务历史。`/healthz` 检查 API 和初始快照可用性，采集是否持续应同时观察快照时间及 worker 日志。

开发前端使用 `npm run dev`，Vite 将 API、认证及历史路径代理到本机 `18080`，保持同源 Cookie 和控制请求。

## 验证

```bash
npm run lint
npm run build
node --test tests/status-utils.test.js
.venv/bin/python -m unittest discover -s tests -v
```

部署后确认两个健康接口、匿名服务历史、受保护路径、本地备用登录、OIDC 跳转以及采集节奏。所有秘密与运行数据均不提交。
