# Lightweight Status Monitor

一个小规模内网状态页：Python worker 采集 HTTP 服务和 Node Exporter 指标，SQLite 保存历史，React 展示当前状态与最近 24 小时趋势。

## 目录

- `backend/status_monitor/worker.py`: 定时采集，写入 SQLite，并生成 `frontend/public/status.json`
- `backend/status_monitor/api.py`: 只读 JSON API
- `frontend/src`: React status page
- `config.json`: 监控目标和采集参数
- `data/status.db`: 默认 SQLite 数据库位置

## 配置

编辑 `config.json`：

```json
{
  "services": [
    { "name": "Site 1", "url": "https://site1.com" }
  ],
  "servers": [
    { "name": "App Server", "target": "100.64.0.10:9100" }
  ]
}
```

`servers[].target` 可以写 `100.x.x.x:9100`，程序会自动请求 `http://100.x.x.x:9100/metrics`。

## 后端运行

Python 3.11+ 即可，不需要额外 pip 依赖。

```bash
python3 -m backend.status_monitor.worker --config config.json --once
python3 -m backend.status_monitor.worker --config config.json
python3 -m backend.status_monitor.api --config config.json --host 127.0.0.1 --port 8080
```

API：

- `GET /status`
- `GET /history/services?hours=24`
- `GET /history/servers?hours=24`

## Docker Compose

```bash
docker compose up --build
```

启动后访问：

```text
http://127.0.0.1:18080
```

Compose 会：

- 构建 React 前端
- 启动 Python worker 定时采集
- 启动 Python API 并服务前端静态文件
- 使用 `status-data` volume 保存 SQLite 数据库
- 挂载当前目录的 `config.json` 到容器内 `/app/config.json`

默认映射到宿主机 `18080` 端口，避免和本地开发 API 的 `8080` 冲突。如需改端口：

```bash
STATUS_PORT=8080 docker compose up --build
```

如果修改了前端代码，需要重新构建：

```bash
docker compose up --build
```

## 前端运行

```bash
npm install
npm run dev
```

如果 API 与 Vite 不在同一地址，设置：

```bash
VITE_STATUS_API=http://127.0.0.1:8080 npm run dev
```

前端每 30 秒刷新一次。API 不可用时，会读取 worker 生成的 `/status.json`。

## 网络流量说明

Node Exporter 原生的 `node_network_receive_bytes_total` 和 `node_network_transmit_bytes_total` 是从网卡启动以来累计增长的 counter，不是最近一分钟流量。

本项目会保存上一轮采集到的 counter，用当前 counter 减上一轮 counter，再按实际间隔归一成 `bytes/min`。第一次采集没有上一轮数据，所以网络流量会显示为空；第二次采集后开始显示最近一分钟估算流量。

## systemd 示例

`/etc/systemd/system/status-worker.service`：

```ini
[Unit]
Description=Lightweight Status Monitor Worker
After=network-online.target

[Service]
WorkingDirectory=/home/anpoliros/status
ExecStart=/usr/bin/python3 -m backend.status_monitor.worker --config config.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/status-api.service`：

```ini
[Unit]
Description=Lightweight Status Monitor API
After=network-online.target

[Service]
WorkingDirectory=/home/anpoliros/status
ExecStart=/usr/bin/python3 -m backend.status_monitor.api --config config.json --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## 数据保留

当前版本不自动删除历史数据。小规模采集下 SQLite 很轻；需要长期运行时，可以定期删除旧数据：

```sql
DELETE FROM service_checks WHERE timestamp < datetime('now', '-30 days');
DELETE FROM server_metrics WHERE timestamp < datetime('now', '-30 days');
```
