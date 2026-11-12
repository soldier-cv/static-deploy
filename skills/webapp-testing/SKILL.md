---
name: webapp-testing
description: Use when 需要对本地 Web 应用做端到端功能测试、DOM 元素交互与行为调试：用 Python Playwright 编写自动化脚本、驱动多服务生命周期（with_server.py）、捕获页面状态与浏览器日志。触发词：webapp-testing、Playwright 测试、Web 功能测试、E2E 测试、DOM 交互、with_server。
version: 1.0.0
author: Hermes coding agent
license: Apache-2.0
metadata:
  hermes:
    tags: [playwright, e2e, testing, browser-automation, webapp]
    related_skills: [ui-diff, frontend-review, api-testing-toolkit]
---

# Web Application Testing

> 版本记录：1.0.0 首发本地 Web 应用 Playwright 交互与功能测试工具包，补齐标准 frontmatter、UI 簇互链与升级段。

> **相关技能**：
> - [ui-diff](../ui-diff/SKILL.md) — 跨平台 UI 截图比对与视觉回归验收
> - [frontend-review](../frontend-review/SKILL.md) — 前端交付审查（信息架构、入口冗余、文案纪律）
> - [api-testing-toolkit](../api-testing-toolkit/SKILL.md) — 纯接口层面自动化故事流测试

To test local web applications, write native Python Playwright scripts.

**Helper Scripts Available**:
- `references/with-server.md` - Manages server lifecycle (supports multiple servers)；按节还原为 `scripts/with_server.py` 后执行

**Always run scripts with `--help` first** to see usage. DO NOT read the source until you try running the script first and find that a customized solution is abslutely necessary. These scripts can be very large and thus pollute your context window. They exist to be called directly as black-box scripts rather than ingested into your context window.

## Decision Tree: Choosing Your Approach

```
User task → Is it static HTML?
    ├─ Yes → Read HTML file directly to identify selectors
    │         ├─ Success → Write Playwright script using selectors
    │         └─ Fails/Incomplete → Treat as dynamic (below)
    │
    └─ No (dynamic webapp) → Is the server already running?
        ├─ No → Run: python scripts/with_server.py --help
        │        Then use the helper + write simplified Playwright script
        │
        └─ Yes → Reconnaissance-then-action:
            1. Navigate and wait for networkidle
            2. Take screenshot or inspect DOM
            3. Identify selectors from rendered state
            4. Execute actions with discovered selectors
```

## Example: Using with_server.py

To start a server, run `--help` first, then use the helper:

**Single server:**
```bash
python scripts/with_server.py --server "npm run dev" --port 5173 -- python your_automation.py
```

**Multiple servers (e.g., backend + frontend):**
```bash
python scripts/with_server.py \
  --server "cd backend && python server.py" --port 3000 \
  --server "cd frontend && npm run dev" --port 5173 \
  -- python your_automation.py
```

To create an automation script, include only Playwright logic (servers are managed automatically):
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True) # Always launch chromium in headless mode
    page = browser.new_page()
    page.goto('http://localhost:5173') # Server already running and ready
    page.wait_for_load_state('networkidle') # CRITICAL: Wait for JS to execute
    # ... your automation logic
    browser.close()
```

## Reconnaissance-Then-Action Pattern

1. **Inspect rendered DOM**:
   ```python
   page.screenshot(path='/tmp/inspect.png', full_page=True)
   content = page.content()
   page.locator('button').all()
   ```

2. **Identify selectors** from inspection results

3. **Execute actions** using discovered selectors

## Common Pitfall

❌ **Don't** inspect the DOM before waiting for `networkidle` on dynamic apps
✅ **Do** wait for `page.wait_for_load_state('networkidle')` before inspection

## Best Practices

- **Use bundled scripts as black boxes** - 先按 `references/with-server.md` / `references/examples.md` 把脚本落到 `scripts/`、`examples/`，再当作黑盒调用。 These scripts handle common, complex workflows reliably without cluttering the context window. Use `--help` to see usage, then invoke directly. 
- Use `sync_playwright()` for synchronous scripts
- Always close the browser when done
- Use descriptive selectors: `text=`, `role=`, CSS selectors, or IDs
- Add appropriate waits: `page.wait_for_selector()` or `page.wait_for_timeout()`

## Reference Files

- **examples/** - Examples showing common patterns:
  - `element_discovery.py` - Discovering buttons, links, and inputs on a page
  - `static_html_automation.py` - Using file:// URLs for local HTML
  - `console_logging.py` - Capturing console logs during automation

## 随附资产对照（分发通道只放行 Markdown）

| 原始路径 | 技能包内位置 |
|---|---|
| `scripts/with_server.py` | `references/with-server.md`（`## scripts/with_server.py` 节） |
| `examples/console_logging.py` | `references/examples.md`（`## examples/console_logging.py` 节） |
| `examples/element_discovery.py` | `references/examples.md`（`## examples/element_discovery.py` 节） |
| `examples/static_html_automation.py` | `references/examples.md`（`## examples/static_html_automation.py` 节） |
| `LICENSE.txt` | `references/license.md`（`## LICENSE.txt` 节） |

> 本技能原带 Python 脚本与示例，已转写为 Markdown；许可证全文见 `references/license.md`。

## 版本与升级（统一走 skillctl）

更新源（唯一权威）：`http://100.64.0.88:8088/.well-known/skills/index.json`

```bash
# 首次：下载通用客户端（每台机器一次）
curl -fsSL http://100.64.0.88:8088/.well-known/skillctl.py -o skillctl.py && chmod +x skillctl.py

# 干活前惰性检查（约 1 秒）：落后就先升级，再动手
./skillctl.py list                                  # 本地各技能版本 vs 注册表
./skillctl.py update --to <你的技能目录>             # 默认只检测（--to 用绝对路径）
./skillctl.py update --to <你的技能目录> --apply     # 确认后才升级（逐文件 sha256 校验）
```

版本语义：`patch` 修错别字不改结论；`minor` 新增章节/接口；`major` 推翻既有结论（需重读全文）。
