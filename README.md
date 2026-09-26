# MIME Multipart 报文检查器

基于 **FastAPI + 原生 HTML/CSS/JavaScript** 的 MIME `multipart/*` 报文解析、
查看、编辑与重新编码工具。严格按 **RFC 2045 / 2046** 处理：

- 🔍 **解析**：粘贴 `Content-Type`、`boundary` 和原始报文，自动识别
  *完整 MIME 报文*（含顶层头部）或 *仅 multipart body*；
- 🪆 **嵌套 multipart**：递归解析 `multipart/mixed`、`multipart/alternative`、
  `multipart/form-data` 等任意 `multipart/*`；
- 📐 **CRLF 边界**：识别 `CRLF "--boundary"` 起始定界符与
  `"--boundary--"` 关闭定界符，校验 transport padding、preamble/epilogue、
  缺关闭定界符、报文截断等；
- 📝 **引号参数**：正确解析 Content-Type 中带引号的 `boundary` 参数、
  分号与反斜杠转义（如 `boundary="a;b"`、`charset="utf\"-8"`）；
- 🔡 **Content-Transfer-Encoding**：识别叶子部分的 `base64` /
  `quoted-printable` / `7bit` / `8bit` / `binary`，把传输正文解码为
  可编辑内容并保留原始编码信息；畸形编码产生带节点路径的诊断且
  不丢失原始载荷；重新编码按头部声明回写并遵守 MIME 折行规则
  （base64 76 列、quoted-printable 76 列软换行），未编辑节点逐字节还原；
- 🩺 **诊断面板**：按 *错误 / 警告 / 提示* 三级列出每个解析问题及所属部分路径；
- ✏️ **可视化编辑**：逐层展开/折叠，编辑任意部分的头部、正文、boundary、
  preamble / epilogue，可新增或删除部分；
- 🔁 **重新编码并下载**：按（可能已修改的）boundary 规则以 CRLF 重新生成报文，
  可选择是否包含顶层头部；未修改的部分逐字节还原（含二进制）。
- 🆚 **样本对比**：把两份解析结果存为样本 A / B（保存在浏览器 localStorage），
  按树路径对齐比较媒体类型、头部、正文编码、boundary、序言/尾注与诊断代码；
  差异以可展开的新增/删除/修改清单展示，点击条目即可在两侧结构树中定位节点，
  并可导出 JSON 差异报告。

---

## 快速开始（Docker）

```bash
docker compose up --build
```

启动后用浏览器访问：

> **http://localhost:8000**

停止：

```bash
docker compose down
```

## 不使用 Compose（docker）

```bash
docker build -t mime-inspector .
docker run --rm -p 8000:8000 mime-inspector
# 浏览器打开 http://localhost:8000
```

## 本地开发（Python 3.11+）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

访问 http://localhost:8000 ；交互式 API 文档在
http://localhost:8000/docs 。

---

## 使用说明

1. 在顶部选择一个内置示例（**表单 / 嵌套 / 错误报文**），或直接粘贴：
   - **Content-Type**（可选）：例如
     `multipart/form-data; boundary="----xyz"`；留空则从报文头部读取；
   - **boundary**（可选）：单独填写，会覆盖 Content-Type 中的参数（可带引号）；
   - **原始报文**：完整 MIME 报文或 multipart body 均可，支持 CRLF / LF。
2. 点击 **解析报文**，查看诊断信息与树形结构。
3. 展开任意 multipart 节点，修改 boundary、头部、正文、preamble/epilogue，
   或增删子部分。声明了 `Content-Transfer-Encoding: base64` /
   `quoted-printable` 的叶子部分会显示**已解码**的正文，可直接编辑；
   也可用节点内的「传输编码」下拉把该部分**切换为 base64 /
   quoted-printable**（即改写其 CTE 头部），随后重新编码下载即按新编码输出。
4. 勾选/取消“编码时包含顶层头部”，点击 **重新编码并下载**。
5. 在结果区可重新下载、复制为文本，或查看编码后的完整报文。
6. **样本对比**（页面底部「4. 样本对比」卡片）：
   - 解析一份报文后点击结构区右上角的 **存为样本 A**；再解析（或编辑后重新解析）
     另一份报文，点击 **存为样本 B**。样本保存在浏览器 localStorage，刷新不丢失；
   - 点击 **开始对比**，查看按树路径对齐的差异清单（新增 / 删除 / 修改 / 未变化，
     可点击徽章筛选），展开条目查看字段级 A/B 对照；
   - 点击条目右侧的 **A** / **B** 按钮，在下方对应的只读结构树中高亮定位该节点；
   - 点击 **导出 JSON 差异报告** 下载 `mime-diff-report.json`。

> 不是合法 UTF-8 的正文（如二进制附件）会以 **base64** 呈现；只要不修改，
> 重新编码时会逐字节还原。对声明了 base64 / quoted-printable 传输编码的
> 部分，编辑器展示的是**解码后**的内容；未编辑时重新编码回写**原始载荷**
> （含原始折行），保证字节稳定。

---

## Content-Transfer-Encoding 语义

叶子部分（`kind: "part"`）按 RFC 2045 §6 处理 `Content-Transfer-Encoding`：

| 声明值 | 解析行为 | 重新编码行为 |
| --- | --- | --- |
| `base64` | 忽略载荷中的折行空白后解码；非法字符 / 错误 padding 记 `CTE_BASE64_INVALID`（错误），正文区展示**原始载荷** | 未编辑时回写原始载荷（含原始折行）；编辑后按 76 列 CRLF 折行重新编码 |
| `quoted-printable` | 解码 `=XX` 与软换行 `=CRLF`；畸形 `=` 序列记 `CTE_QP_INVALID`（警告）并按原样保留 | 未编辑时回写原始载荷；编辑后按 RFC 2045 §6.7 重新编码（行尾空白编码为 `=20`/`=09`，76 列软换行） |
| `7bit` / `8bit` | 不解码；含高位 / NUL 字节记 `CTE_7BIT_VIOLATION` / `CTE_8BIT_VIOLATION`（警告） | 原样输出 |
| `binary` | 不解码、不校验 | 原样输出 |
| 其他值 | 记 `CTE_UNKNOWN`（警告），按未编码（7bit 语义）处理 | 原样输出并再次给出 `CTE_UNKNOWN` |
| 未声明 | 按 7bit 语义展示 | 原样输出 |

补充规则：

- `multipart/*` 节点声明 base64 / quoted-printable 会记 `CTE_ON_MULTIPART`
  （警告，RFC 2045 §6.4）并忽略；
- 编码方式以**节点当前的 CTE 头部**为准：直接编辑头部或用前端下拉切换
  （base64 ↔ quoted-printable）都会按新声明回写；
- 解析时解码失败的部分，正文即原始载荷，编码时原样回写绝不二次编码；
  此时若变更了编码方式，记 `CTE_NOT_CONVERTED`（警告）。

---

## 解析规则与诊断代码

解析器采用“尽量恢复、绝不轻易失败”的策略：能继续解析的问题记录为 issue，
而不是中断。常见诊断：

| 代码 | 级别 | 含义 |
| --- | --- | --- |
| `NO_DELIMITER` | 错误 | 正文中找不到任何 `--boundary` |
| `MISSING_CLOSE_DELIMITER` | 错误 | 缺少 `--boundary--`，报文可能被截断 |
| `TRUNCATED_PART` | 错误 | 某部分之后缺少结束该部分的 CRLF |
| `BAD_DELIMITER` | 错误 | 定界符后存在非法字符，或出现碰撞文本 |
| `MISSING_BOUNDARY` | 错误 | `multipart/*` 的 Content-Type 无 boundary 参数 |
| `BOUNDARY_COLLISION` | 错误 | （编码时）正文行首出现本层定界符，会截断报文 |
| `BAD_HEADER_LINE` / `BAD_HEADER_NAME` | 错误 | 头部缺少冒号 / 字段名非法 |
| `BAD_QUOTED_STRING` / `BAD_PARAM_SYNTAX` | 错误 | 引号未闭合 / 参数语法错误 |
| `LF_NORMALIZED` | 警告 | 输入含孤立 LF/CR，已规范化为 CRLF |
| `BOUNDARY_NONCOMPLIANT` | 警告 | boundary 超过 70 字符或含非法字符 |
| `BOUNDARY_OVERRIDE` | 警告 | 输入框/Content-Type 中的 boundary 不一致 |
| `TRAILING_PADDING` | 警告 | 定界符后存在 transport padding 空白 |
| `NO_LEADING_CRLF` | 提示 | 首定界符前无 CRLF（HTTP multipart 常见） |
| `PREAMBLE` / `EPILOGUE` | 提示 | 存在序言 / 尾注，MIME 处理器应忽略 |
| `BINARY_BODY` | 提示 | 该部分为非文本，已按 base64 呈现 |
| `CTE_BASE64_INVALID` | 错误 | base64 载荷畸形（非法字符 / padding），已保留原始载荷 |
| `CTE_UNKNOWN` | 警告 | 无法识别的 Content-Transfer-Encoding，按 7bit 语义处理 |
| `CTE_QP_INVALID` | 警告 | quoted-printable 含畸形 `=` 序列，已按原样保留 |
| `CTE_7BIT_VIOLATION` / `CTE_8BIT_VIOLATION` | 警告 | 声明 7bit/8bit 但正文含高位 / NUL 字节 |
| `CTE_ON_MULTIPART` | 警告 | multipart 不允许 base64/QP 传输编码（RFC 2045 §6.4） |
| `CTE_NOT_CONVERTED` | 警告 | （编码时）原始编码畸形，内容未随编码方式变更转换 |

---

## HTTP API

### `POST /api/parse`

请求：

```json
{
  "raw": "Content-Type: multipart/form-data; boundary=B\r\n\r\n--B\r\n\r\nv\r\n--B--",
  "rawBase64": "...(可选，二进制无损通道，优先于 raw)...",
  "contentType": "multipart/form-data; boundary=B",
  "boundary": "B"
}
```

响应（节选）：

```json
{
  "ok": true,
  "mediaType": "multipart/form-data",
  "effectiveBoundary": "B",
  "hasTopHeaders": true,
  "counts": { "error": 0, "warning": 0, "info": 0 },
  "issues": [ { "level": "warning", "code": "LF_NORMALIZED", "message": "..." } ],
  "tree": {
    "kind": "multipart",
    "mediaType": "multipart/form-data",
    "boundary": "B",
    "leadingCrlf": false,
    "headers": [ { "name": "Content-Type", "value": "..." } ],
    "preamble": "", "preambleEncoding": "utf-8",
    "epilogue": "", "epilogueEncoding": "utf-8",
    "parts": [ {
      "kind": "part",
      "mediaType": "text/plain",
      "headers": [],
      "hasHeaders": false,
      "body": "v",
      "bodyEncoding": "utf-8",
      "cte": null,
      "cteDecoded": false
    } ]
  }
}
```

叶子部分（`kind: "part"`）与传输编码相关的字段：

| 字段 | 含义 |
| --- | --- |
| `cte` | 归一化（小写）的 Content-Transfer-Encoding 声明值；未声明为 `null` |
| `cteDecoded` | base64 / quoted-printable 是否解码成功；失败时 `body` 为原始载荷 |
| `body` / `bodyEncoding` | 解码后的可编辑内容及其呈现编码（`utf-8` 或 `base64`） |
| `cteRaw` / `cteRawEncoding` | 原始传输载荷（仅 base64/QP 部分返回）；未编辑时编码端逐字节回写 |

### `POST /api/encode`

请求：

```json
{ "tree": { /* /api/parse 返回的 tree，可修改 */ }, "includeHeaders": true }
```

响应：

```json
{
  "ok": true,
  "payloadBase64": "Q29udGVudC1UeXBlOi...",
  "size": 123,
  "lineEnding": "CRLF",
  "counts": { "error": 0, "warning": 0, "info": 0 },
  "issues": []
}
```

编码端按各叶子部分**当前的** `Content-Transfer-Encoding` 头部回写正文：
`base64` 按 76 列折行、`quoted-printable` 按 76 列软换行；未编辑且编码
方式未变的部分直接回写原始载荷（字节稳定）；修改或删除该头部即切换
编码方式（例如把 `base64` 改为 `quoted-printable` 即完成转码）。

### `POST /api/diff`

样本对比：按树路径对齐比较两份解析结果。请求中的 `tree` / `issues`
直接取自两次 `POST /api/parse` 的响应（`issues` 可省略，省略则不对比诊断代码）。

请求：

```json
{
  "a": { "tree": { /* 样本 A 的 tree */ }, "issues": [ /* 样本 A 的 issues */ ] },
  "b": { "tree": { /* 样本 B 的 tree */ }, "issues": [ /* 样本 B 的 issues */ ] }
}
```

响应（节选）：

```json
{
  "ok": true,
  "summary": { "added": 1, "removed": 0, "modified": 2, "unchanged": 3 },
  "previewLimit": 400,
  "entries": [
    {
      "path": "root",
      "kind": "multipart",
      "change": "modified",
      "fields": [
        { "field": "boundary", "label": "boundary",
          "a": { "text": "AA", "truncated": false, "length": 2 },
          "b": { "text": "BB", "truncated": false, "length": 2 } },
        { "field": "headers", "label": "头部",
          "added": ["X-New: 1"], "removed": [], "reordered": false,
          "aCount": 1, "bCount": 2 },
        { "field": "issues", "label": "诊断代码",
          "added": ["PREAMBLE"], "removed": [] }
      ]
    },
    {
      "path": "parts[2]",
      "kind": "part",
      "change": "added",
      "summary": { "mediaType": "application/json", "rawSize": 42,
                   "descendantParts": 0, "headers": 1 },
      "fields": []
    }
  ]
}
```

说明：

- `change` 取值：`added`（仅 B 有）/ `removed`（仅 A 有）/ `modified` / `unchanged`；
  增删的子树整体折叠为一条，`summary.descendantParts` 给出后代部分数量；
- `path` 为 `""` 的条目表示**全局诊断**变化（如 `LF_NORMALIZED` 这类不归属
  任何节点的 issue）；
- 长文本字段（正文、序言/尾注）以预览形式返回，`truncated: true` 时
  `length` 为完整长度（上限见 `previewLimit`）。

### `GET /api/health`

返回 `{"ok": true}`，供容器健康检查使用。

---

## 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用、/api/parse、/api/encode、/api/diff、静态文件
│   ├── mime.py              # 零第三方依赖的 MIME 解析 / 重新编码核心
│   ├── diff.py              # 样本对比：按树路径对齐的字段级差异计算
│   └── static/
│       ├── index.html       # 页面结构
│       ├── styles.css       # 深色主题样式
│       └── app.js           # 原生 JS：示例、树形编辑器、样本对比、下载
├── tests/
│   └── smoke_test.py        # 解析/编码/对比端到端测试（仅需 Python 标准库）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 运行测试

测试不依赖 FastAPI，只用 Python 标准库：

```bash
python3 tests/smoke_test.py
```

覆盖：基本 form-data、CJK、嵌套 multipart、preamble/epilogue、
引号与转义参数、boundary 覆盖、定界符碰撞、缺关闭定界符、LF 规范化、
二进制逐字节往返、编辑后重新编码、Content-Transfer-Encoding
（base64/QP 解码与折行回写、畸形编码诊断与原始载荷保留、编码方式切换），
以及样本对比（节点增删折叠、字段级差异、头部逐行对比、诊断代码归属与全局诊断）。

---

## 安全说明

- 该工具用于**本地检查报文**，默认只监听容器的 `8000` 端口；请勿直接暴露到公网。
- 所有解析都在内存中完成，请求不会转发到任何第三方。
- 二进制正文以 base64 在前后端之间传输，避免编码损坏。
