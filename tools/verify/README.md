# tools/verify — 独立验收脚本

随代码入库，改动 MCP 端点或上传链路后直接复跑，不要重新手搓。

| 脚本 | 依赖 | 覆盖 |
|---|---|---|
| `../selftest_mcp.py` | 纯标准库 | 18 项：MCP 协议握手/错误码、三工具端到端、越界与非法输入、测试数据自清理 |
| `sd_mcp_client_check.py` | `mcp` SDK + `httpx` | 真实 MCP 客户端路径：initialize → tools/list → 两种部署 → 链接可访问 → 清理 |
| `sd_mcp_adversarial.py` | 纯标准库 | 超大输入、zip slip（/api/deploy）、5 并发原子写、顶层目录入口回归、测试数据清理 |
| `sd_stdio_check.py` | 纯标准库 | 本机 stdio 客户端脚本（`client-mcp/mcp_server.py`，按本地路径上传） |

## 用法

```bash
# 纯标准库脚本
python3 tools/selftest_mcp.py http://127.0.0.1:8088
python3 tools/verify/sd_mcp_adversarial.py http://127.0.0.1:8088
python3 tools/verify/sd_stdio_check.py 127.0.0.1 8088

# SDK 脚本（需要 mcp + httpx 的环境）
python3 -m venv /tmp/sdv && /tmp/sdv/bin/pip install mcp httpx -i https://pypi.tuna.tsinghua.edu.cn/simple
/tmp/sdv/bin/python tools/verify/sd_mcp_client_check.py http://127.0.0.1:8088
```

所有脚本都会清理自己创建的项目；`sd_stdio_check.py` 会在 `/home/xl/tmp/coding/builds/stdio_demo` 造一个临时原型目录。
