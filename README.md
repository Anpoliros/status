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

## 本地管理 Prometheus 主机与下发

在 general 中使用 `collectors` 声明 Prometheus 来源：

```json
{
  "collectors": [
    {
      "type": "prometheus",
      "id": "prometheus-ali-150",
      "url": "http://100.123.29.123:9090",
      "job": "pusr-node",
      "file": "configs-pusr/resources/ali.prometheus.json",
      "deploy": {
        "ssh_host": "ali-150-root",
        "target_file": "/etc/prometheus/targets/pusr-node.json"
      }
    }
  ]
}
```

`file` 支持绝对路径或仓库根目录相对路径。`.prometheus.json` 由 collector 专门加载，resource 目录扫描跳过它，避免重复直连采集。每个文件结构如下：

```json
{
  "servers": [
    { "id": "ali-ecs-142", "name": "142", "target": "10.1.2.142:9100", "cluster": "dgroup" }
  ]
}
```

主机 ID 在整个 status 实例内唯一，不包含 collector 身份；改名、换地址或换 collector 时保持 ID 即保留历史。同一地址不能同时配置两个身份。第一次迁移按旧地址认领已有数据库行，保留整数主键、原始记录和历史聚合；移除主机只停用，不删除记录。重新使用已有地址代表另一台主机时，应先显式处理旧主机的地址占用，避免误合并历史。普通直连机器也支持稳定 `id`。

collector 的 `name` 和 `cluster` 在本地维护，不发送到 Prometheus；调整展示不需要下发。默认只下发 `status_id`、`status_enabled` 标签，指标查询按 `status_id` 关联。CPU 与网络速率采用 5 分钟范围计算，确保 60 秒采集周期下有足够样本；新标签首次生效时需至少两轮采集。需要 Prometheus 告警按集群查询时，可开启 `export_cluster_label: true`；此时 cluster 会进入时间序列标签。旧的 `prometheus` 发现配置暂时兼容，新配置应使用 collectors。

首次需要在远端的对应 scrape job 使用 `file_sd_configs` 指向 `target_file`，保留原有 scrape interval、relabeling 等设置并校验、重载一次。以后只更新 JSON 清单，Prometheus 文件监视会自动应用，无需重启或重载。远端为 Docker 部署时应挂载目标目录，保证原子替换对容器可见。

本地应准备与远端版本一致的 `promtool`（生产当前为 `data/tools/promtool-ali-150`，工具不提交）：

```bash
# 默认预览；完成本地校验、版本匹配检查，并显示远端差异。
.venv/bin/python configs/scripts/deploy-prometheus.py \
  --config configs-pusr/general.json --collector prometheus-ali-150 \
  --promtool data/tools/promtool-ali-150 --dry-run

# 校验后下发，并验证 Prometheus targets API 的 ID 与地址。
.venv/bin/python configs/scripts/deploy-prometheus.py \
  --config configs-pusr/general.json --collector prometheus-ali-150 \
  --promtool data/tools/promtool-ali-150 --apply
```

脚本使用 SSH 别名的认证，不在配置里保存 SSH 密钥。目标清单先通过本地结构校验与同版本 promtool 校验，上传后再次使用远端 promtool 校验临时清单及主配置，取得文件锁并检查远端内容未被其他部署修改，最后原子替换。已有文件保存在同目录 `.previous`，必要时将备份原子恢复即可。清空全部目标需要显式传入 `--allow-empty`。

`--dry-run` 不写远端文件；`--apply` 不重载主配置。下发只修改指定 File SD 文件，不覆盖其他 jobs。目标离线会报告，但不自动回滚整份清单；目标及标签发现不匹配则命令失败，保留备份供排查。Prometheus 2.31 不提供 `promtool check service-discovery`，而旧版 `check config` 不会深入校验 File SD 内容，因此包装配置同时将生成结果作为 `static_configs` 交给 promtool 校验，再通过运行中的 targets API 验证实际发现结果。

本地配置修改后还需重启相应 status worker/API，读取新的名称、分组与清单。服务身份机制本次保持不变。

### 可选的 SSH 隧道采集

直连 Node Exporter 和 Prometheus 的配置与采集方式保持原样。仅在普通 `servers` 条目显式声明 `transport` 时，才通过 SSH 隧道访问 exporter：

```json
{
  "servers": [
    {
      "id": "mml",
      "name": "mml",
      "cluster": "x2",
      "target": "10.176.46.12:9100",
      "transport": { "type": "ssh", "host": "mml-ranges-jump" }
    }
  ]
}
```

`host` 是运行 status 用户的 `~/.ssh/config` 别名，可继续配置 `ProxyJump`、用户名、密钥与 known_hosts。需要提前确认非交互 SSH 登录和主机密钥验证正常。SSH transport 要求显式稳定 `id`；数据库始终保留原始 `target` 和 ID，切换传输不会新建主机或丢失历史。

`target` 是 SSH 目标机视角下的 HTTP exporter 地址，必须与 exporter 实际监听地址对应；可使用完整 HTTP URL 保留路径和查询参数。当前 SSH transport 不支持 HTTPS；原有直连 HTTPS 不受影响。

```bash
# 默认仅校验 SSH 配置、生成的 systemd unit，不连接远端、不安装服务。
.venv/bin/python configs/scripts/deploy-ssh.py --config configs-pusr/general.json --check

# 安装/更新此实例的 systemd 用户服务，并实际探测 exporter 指标。
.venv/bin/python configs/scripts/deploy-ssh.py --config configs-pusr/general.json --apply

# 停止并移除此配置路径对应的全部隧道。
.venv/bin/python configs/scripts/deploy-ssh.py --config configs-pusr/general.json --remove
```

隧道独立于采集周期常驻，由 systemd 自动重启，SSH 心跳检测断线。本地端口仅监听 `127.0.0.1`，自动根据配置文件绝对路径和主机 ID 生成，也可在 transport 中指定 `local_port`（1024–65535）；本实例重复端口会在加载配置时报错。跨实例或其他进程占用端口时，隧道启动失败，可改用显式端口。配置路径移动或变更 ID 前，先使用旧配置执行 `--remove`，避免遗留服务。

首次部署需确保用户 systemd 可用，并运行 `loginctl enable-linger 用户名`，让用户服务开机启动且退出 SSH 后继续运行。脚本生成的 unit 名称可用于 `systemctl --user status UNIT` 和 `journalctl --user -u UNIT`。脚本只管理所选配置路径对应的 unit；`--apply` 会清理该实例已经移除的隧道。探测失败时命令报错，保留服务供重连和排查。

启用时先执行隧道 `--apply`，然后重启对应 status worker/API。恢复直连时，删除 transport 并重启对应实例，再执行 `--apply` 清理旧隧道。采集失败会按原有逻辑写入缺失测量，不把旧值伪装成新值；采集器不会按浏览器请求创建 SSH 连接。

### 筛选与排序

集群顺序默认遵循资源配置；Filter 与页面使用同一顺序。点击集群标题折叠，长按标题或直接拖动右侧手柄可排序；拖动时显示插入位置，松手后保存，并支持滚动菜单。键盘聚焦标题后可用 Alt + 上/下箭头调整顺序。

Status 与 History 共享同一资源类型的集群顺序，各自保留筛选和折叠状态；机器与服务设置分开保存。Name、CPU 等显示排序只影响集群内部的机器，不会改变集群排列。上述设置保存在当前浏览器。

## 本地服务流量与 TCP

服务条目可选配置 `"metrics": {"port": 1638}`，端口为本机应用监听端口。
每 10 秒独立采集 TCP ESTABLISHED 数量和流量；不依赖 HTTP 健康探测周期。
当前只支持 cloudflared 与应用通过本机 loopback TCP 通信的部署。
统计包括本地调用、HTTP 探测、IP/TCP 开销与重传，不包括 Cloudflare 缓存命中；
连接数包括空闲连接池和长连接，不代表访客人数。连接统计按本地端口，包括该端口的非 loopback 连接。

### 一次安装流量计数器

审核 `configs/scripts/ports.json` 中的端口列表后，在仓库根目录执行：

```bash
sudo sh configs/scripts/install-port-counters.sh
```

安装脚本把 helper 和端口清单复制到 root 管理的 `/usr/local/lib/status-ports`，
建立 `status-ports.service`。它仅管理独立 nftables 表 `inet status_ports`，
在 output hook 对 loopback 上的服务源/目的端口分别计数，不添加丢弃或放行规则。
不应使用全局 `nft flush ruleset`；外部防火墙重载若删除此表，重启该服务重建即可。
每 5 秒原子发布 `/run/status-ports/counters.json`；status 无需 sudo 或 root。
更新端口清单后重新执行安装命令。移除时停止并禁用 systemd 服务，
再删除专用 nftables 表与已安装文件。

未安装或计数文件超时，TCP 仍可用，流量显示缺失；第一轮样本只建立基线。
计数器重置或采集中断超过 30 秒重新建立基线，不跨缺失区间推算流量。
累计量仅代表已观察区间。原始数据保留 24 小时，小时/日聚合保留 61 天。
页面提供近一小时分钟均值、24 小时小时均值、60 天日均值，今日累计与 TCP 峰值；
日期以 UTC 划分。指标仅经受保护的 `/status` 发布，匿名服务健康历史不含流量数据。
