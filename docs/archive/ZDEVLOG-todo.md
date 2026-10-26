

改进服务可用性探测方式
- /health页面
- 多种时延计算：dns tcp tls ttfb


我们来增加一个api，快速判断服务是否可用，并且制作一个可复用的快速检测卡片，方便在其他页面快速判断服务状态。

1. api /check
不返回所有status。如果所有监控项目都绿，返回{"overall_status": "healthy"}；如果有人红了，返回attention和不可用的服务/服务器名字；三个以上红的，返回alert和不可用名字。

2. 快速检测卡片
组件初始化时触发一次/check，