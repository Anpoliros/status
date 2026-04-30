构建一个轻量级的服务与服务器状态监控系统（类似 Better Stack 的 status page），系统规模较小（<10 个服务，3 台服务器），要求简单可靠、易部署。

## 一、总体架构

系统分为三个部分：

1. Python 后端（监控与数据聚合）
2. 数据库（存储历史监控数据）
3. React 前端（展示 status page）

系统运行在内网环境（通过 Tailscale 访问服务器）

---

## 二、监控目标

### 1. 服务监控（HTTP）

- 监控数量：<10
- 监控方式：HTTP GET
- 指标：
  - 是否可用（成功/失败）
  - 响应时间（latency, ms）
- 频率：每 10 分钟一次

---

### 2. 服务器监控

每台服务器运行 Node Exporter，通过 HTTP 暴露 metrics：

示例：
http://<tailscale_ip>:9100/metrics

需要采集：

- CPU 使用率
- 内存使用率
- 磁盘使用率
- 网络流量（in/out）

采集频率：每 1 分钟

---

## 三、后端（Python）

实现一个监控 worker（可用 asyncio 或简单 cron loop）：

### 功能：

1. 定时任务：
   - 每 1 分钟抓取服务器 metrics
   - 每 10 分钟检测服务状态

2. 数据解析：
   - 解析 Node Exporter 的 Prometheus 格式
   - 提取关键指标（CPU、内存等）

3. 状态判断：
   - 连续 N 次失败才标记为 down（例如 N=3）

4. 数据存储：
   - 写入数据库（见 schema）

5. 聚合输出：
   - 生成一个 status.json 文件，用于前端读取

### 配置

有一个统一的配置文件，格式形如
```json
{
   "services": [
      "site1.com",
      "site2.com"
   ],
   "servers": [
      "10.1.1.1:9100",
      "10.1.1.2:9100"
   ]
}
```


---

## 四、数据库设计

使用关系型数据库（PostgreSQL 或 SQLite）。

需要以下表：

### 1. services

- id
- name
- url

### 2. service_checks

- id
- service_id
- timestamp
- latency_ms
- status（up/down）

### 3. servers

- id
- name
- ip（tailscale）

### 4. server_metrics

- id
- server_id
- timestamp
- cpu_usage
- memory_usage
- disk_usage
- network_in
- network_out

---

## 五、API 设计

提供简单只读接口：

- GET /status → 当前状态（聚合）
- GET /history/services → 服务历史
- GET /history/servers → 服务器历史

---

## 六、前端（React）

实现一个类似 Better Stack 风格的 status 页面：

### 页面内容：

1. 服务列表
   - 当前状态（up/down）
   - 延迟

2. 服务器状态
   - CPU / 内存 / 磁盘 / 网络

3. 历史趋势（简单图表）
   - 最近 24 小时

### 数据获取：

- 从 /status 或 status.json 拉取
- 每 30 秒自动刷新

---









## 七、非功能要求

- 系统必须在无公网环境下可运行（依赖 Tailscale）
- 前端页面可静态部署（如 GitHub Pages）
- 后端与前端解耦
- 代码结构清晰，便于后续扩展

---

## 八、可选优化

- 数据保留策略（例如只保留 7 天）
- 简单告警（日志或 webhook）
- 状态缓存（避免频繁查询数据库）





---

效果很好！我们来做几个优化

1. 让servers中的服务器卡片可以收起，收起时仅显示健康状态

2. server的network统计最近一分钟的网络流量，而非历史所有。如果node_exporter原生做不到请告诉我 

3. 让整个项目可以docker compose一键启动


---

很好，我们再做几个调整

1. servers中的服务器卡片默认收起，而且加入像service一样的左侧小绿点

2. servers中的服务器卡片收起时，第二行仅显示网络，控制server卡片高度和service一致

3. service和server的展示顺序按照config.json中的来

另外，services中的Up xxx ms的值都是1000+，有点不符合实际，现在是如何判断这个延时的？


---

更改了latency之后不显示