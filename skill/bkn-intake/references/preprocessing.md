# 材料预处理（references/preprocessing.md）

> **本件是什么**：把二进制/半结构化材料变成**可检索、可定位、可入库**的文本形态。
> **只改形态，不改内容**：不重写语义、不补写、不猜测；原文有争议处保留原样并登记待确认。
> **边界**：本仓**没有**灌库脚本（doc/optimize/24-ontology-build-sources.md 源清单第 8 条（文件第 39 行）：**灌库脚本不在本仓库**）；
> 实际入库执行在仓外 chunk 项目 ＋ 外部 skill demo-product-knowledge-ingestion。本件只管**产出入库前的文本**。

---

## 1. docx → 文本：scripts/extract_docx.py（真实用法）

**为什么需要**：doc/projectdoc/ 的官方文档是 .docx（二进制 zip），**不能用 grep 检索**（doc/projectdoc/INDEX.md 第 4 行）；
且必须**能只抽目标章**——Demo Product 9.1.5 用户指导手册有 257 个标题，全量展开既慢又刷屏。

| 参数 | 作用 | 示例 |
|---|---|---|
| `--list` | 列出 doc/projectdoc 下的 .docx 与大小 | `python3 scripts/extract_docx.py --list` |
| `--doc` | 文档名（相对 doc/projectdoc/），必填 | `--doc "Demo Product文件输出原理.docx"` |
| `--toc` | 只输出标题骨架 | `python3 scripts/extract_docx.py --doc "Demo Product文件输出原理.docx" --toc` |
| `--chapter` | 从匹配该前缀的标题抽到下一个同级或更高级标题 | `--chapter "3.5.6"` |
| `--all` | 输出全部正文 | `--doc "Demo Product文件输出原理.docx" --all --out /tmp/f.txt` |
| `--max-lines N` | 截断行数（0＝不限） | `--max-lines 200` |
| `--out PATH` | 写入文件（默认 stdout） | `--out /tmp/f.txt` |

**退出码**：0 成功；1 文档不存在 / 读不出；2 参数错；3 指定章节未找到。

**抽取行为（实证，写文档时别漏）**：

- 遍历 `word/document.xml` 的正文顺序，`w:p` 段落（读 `pPr/w:pStyle` 判层级）与 `w:tbl` 表格（行内以竖线连接，单元格内多段以「 ; 」分隔）都抽。
- 段落内 `w:br` / `w:cr` 是官方文档的换行方式（「检查命令 / 修改命令」写在同一段落里）——只取 `w:t` 会把命令**串成一串**（`sysctl ...tcp_memsysctl ...tcp_rmem`）。
- 递归下降容器节点（`w:sdt` / `w:sdtContent` / `mc:AlternateContent`）——只遍历 body 直接子元素会**整篇漏空**。
- 标题层级兼容两种写法：`Heading N` 与纯数字样式 `2` / `3` / `4`。

**⚠️ 已踩的坑（doc/optimize/61-ontology-completion-plan.md §6 修正 2）**：**数据库产品线常见排错手册.docx 有 0 个 `w:pStyle` 标题**（标题是普通段落）⇒ `--toc` / `--chapter` 不可用，必须 `--all` 后按内容分节；产品 HA 高可用配置手册.docx 与 Oracle 不锁表文档各只有 1 个标题块，同样走 `--all`。
**做法**：先 `--toc` 看骨架；抽不到骨架的文档直接 `--all` ＋ `--out` 落临时文本，再按内容切分。

## 2. xlsx → 文本：scripts/gen_error_codes.py（真实用法）

**extract_docx.py 不处理 xlsx**（它只读 `word/document.xml`）。官方码表 错误代码定义.xlsx 的抽取走专用生成器：

| 命令 | 作用 | 退出码 |
|---|---|---|
| `python3 scripts/gen_error_codes.py` | 由官方码表生成 plugin/error_codes.yaml | 0 成功 |
| `python3 scripts/gen_error_codes.py --check` | 只比对，不一致退出 | 3 不一致；1 源文件缺失；2 解析失败 |
| `python3 scripts/gen_error_codes.py --report` | 只打印覆盖度，不写文件 | 0 |

**表的实际形状（实测，勿再按「267 行」称）**：sheet1 共 267 行，其中 **91 行是空行**，**176 行有内容且 `define` 唯一**；`code`（数字）列有 1 个重复值 `4217`（两个不同 ALARM 定义）⇒ **本表以 `define` 为键**，`code` 只作字段。
**三张 sheet 合并且不是重复**：sheet1 码表 / sheet2 告警表 / sheet3 同列 ＋ old define（sheet2/3 的中文更长时优先）。
**出入**：`plugin/error_codes.yaml` 是 **Tool 层侧车**，**不进本体**（bkn/ 不得引用；Q27）。

## 3. 编码与换行

| 项 | 口径 | 依据 |
|---|---|---|
| 编码 | 抽取器以 **UTF-8** 写文件（`open(..., "w", encoding="utf-8")`） | scripts/extract_docx.py 末段 |
| 换行 | 抽取器内部用 `LF = chr(10)` 拼接；产出为 **LF** | scripts/extract_docx.py 前半 |
| 入库前 | 统一 **LF**（CRLF → LF）、统一 UTF-8，再交外部灌库 | 仓内脚本一律 LF 口径 |

**待确认**：官方 .docx 内是否含 CRLF 段落换行、外部 chunk 项目对 CRLF 的处理口径——本仓**未见**该判别器实现，落库前请以外部项目为准，遇到再登记。

## 4. frontmatter / 标题保留（进 payload）

**为什么**：Qdrant 的 payload 里 `title` 是 **UUID 文件名**（如 `7cfca395-a68c-47ee-ba43-d4b2426ca1d9.docx`）、`doc_summary` **全部为空**、`document_id` 只有一个值（`<data>/public/chunk/web/uploads`）
⇒ **无法从检索结果反查「这段话出自哪份官方文档」**（doc/projectdoc/QDRANT_MAP.md 第 3-5 行）。已知一例扩展名不符：Qdrant 里的 `7ac76854-...xls` 实为 **错误代码定义.xlsx**（同上第 25 行）。

**预处理要求**：

1. 每份材料带 **title（原始文件名 / 章节标题）** 与 **source_path（仓内相对路径或仓外绝对路径）** 进 payload；
2. 能定位到章节的，chunk 级带章节号；
3. 无法唯一锁定的，**标「未定」，不猜**（QDRANT_MAP.md 第 5 节的精确锁定做法：取独有长句 ≥20 字逐 UUID 子串匹配）。

## 5. category 标注（防概念混淆）

同一份材料里「库」这个词至少有两类对象，**必须打 category 标注**，否则抽取/入库后概念互相污染：

| category | 指什么 | 证据 |
|---|---|---|
| 控制台元数据库 | 控制台（webconsole）自己的元数据存储 **postgres**；**不建独立对象**（不算 Demo Product 服务进程） | doc/_archived/optimize-plans/20-runtime-object-ontology.md 第 229、236 行（webconsole ─► postgres 控制台元数据存储） |
| 同步引擎库矩阵 | Demo Product 作为**源端/目标端**支持的库与版本；**源端与目标端两张词表，不得交叉** | `plugin/schemas.py` 与 `.bkn` 字段（源端 / 目标端两字段，硬约定「**不得交叉**」；原 doc/update/64-dbtypes-split.md，2026-10-15 清理） |
| 不支持/预留 | 目标端 `kafka` / `hive` / `starrocks` 等**预留**值（有模式用到再补） | `plugin/schemas.py`（原 doc/update/64-dbtypes-split.md §2，2026-10-15 清理） |

**纪律**：登记材料时逐份写 category；正文出现「PostgreSQL / 数据库」时按上下文判它是**控制台底座**还是**源/目标库**，判不了进待确认清单。

## 6. 二进制附件不入库

| 项 | 口径 | 依据 |
|---|---|---|
| .docx / .xlsx 本体 | 抽取器只读 `word/document.xml`（xlsx 走 gen_error_codes.py），**图片 / 嵌入对象 / 附件（word/media/ 等）不抽取、不入库** | scripts/extract_docx.py 的 `zipfile` 读取范围 |
| 二进制件是否入 git | **不入**：.gitignore 只忽略 `doc/projectdoc/*.docx` 与 `doc/projectdoc/*.xlsx`；台账（INDEX.md / QDRANT_MAP.md）与抽取产物仍入库 | .gitignore 末两条；doc/optimize/61-ontology-completion-plan.md §7 的 R-2 裁定 |

## 7. 「中文文件名 ＋ CRLF 被误判 binary」的坑

**现象**：外部 chunk 管线上，名字含中文、内容含 CRLF（或 GBK 字节）的文本文件**可能被字节级启发式误判为 binary**，从而整份跳过或按二进制处理。
**本仓实证状态**：本仓**没有**该判别器的实现（灌库脚本不在本仓库），上句属**外部管线现象**，机制细节**待确认**。
**落库前自检（不依赖外部实现）**：

1. 逐份确认文本是 **UTF-8 无 BOM、换行 LF**；
2. 用内容而非扩展名判定类型（已知反例：QDRANT_MAP.md 第 25 行 `.xls` 实为 .xlsx）；
3. 中文文件名**保留原名**（便于反查），另在 payload 里带 title，不靠文件名编码；
4. 抽取后抽样 `head` / `file --mime` 复看，发现整份被跳过 → 登记进待确认清单，不强行改内容。

## 8. 预处理验收命令

| 检查 | 命令 |
|---|---|
| 文档清单与大小 | `python3 scripts/extract_docx.py --list` |
| 标题骨架 | `python3 scripts/extract_docx.py --doc "<名>" --toc` |
| 目标章抽取 | `python3 scripts/extract_docx.py --doc "<名>" --chapter "<章节号>"` |
| 全量抽取落盘 | `python3 scripts/extract_docx.py --doc "<名>" --all --out /tmp/<名>.txt` |
| 码表侧车一致性 | `python3 scripts/gen_error_codes.py --check` |

> **不做**：不改 .bkn、不跑 scripts/pending_apply.py、不写 Qdrant（外部库只读检索，doc/projectdoc/QDRANT_MAP.md 第 8 行）。
