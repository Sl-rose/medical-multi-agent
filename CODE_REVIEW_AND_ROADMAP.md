# 团队技术能力提升方案 & 代码质量评审

> 评审人：Senior Developer（高级开发工程师）
> 评审范围：`api.py` / `main_graph.py` / `model/` / `agent/` / 支撑模块 / 数据管线脚本（约 2154 行）
> 目标：给出可落地的代码质量把控机制 + 团队技术成长路线图

---

## 一、总体评价（客观）

### ✅ 做得好的地方（请保持，这是团队的资产）
1. **架构分层清晰**：`api`（接入）→ `main_graph`（LangGraph 编排）→ `agent/*`（业务节点）→ `model`（LLM 封装）→ `session_store`/`medical_safety`（支撑），职责边界明确。
2. **类型意识在线**：`main_graph.AgentState` 用了 `TypedDict`，`api.py` 用了 Pydantic 请求/响应模型，配置走 `dataclass(frozen=True)`。
3. **健壮性有基础**：`model/deepseek.py` 实现了重试 + 指数退避；`main_graph` 对检索 Agent 启动失败做了优雅降级（不拖垮整个服务）；`api` 有 `/api/health` 自检。
4. **安全意识到位**：`medical_safety.py` 抽出了急症关键词拦截、免责声明、边界约束，且被多个 Agent 复用——医疗场景里这是对的。
5. **并发意识**：`agent3` 用 `ThreadPoolExecutor` 做图谱 + 向量双路并发召回，方向正确。
6. **日志规范**：服务与 Agent 层普遍用 `logging` + 结构化日志（`JsonFormatter`），可读性好。

### ⚠️ 当前定位
这是一套**原型级（prototype-grade）**实现，距离**生产级（production-grade）**还差三道关：**类型契约、质量门禁（lint/format/test/CI）、依赖与配置纪律**。下面按优先级给清单。

---

## 二、优先修复清单（P0 / P1 / P2）

### 🔴 P0 — 正确性 / 可运行性（必须马上修）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| P0-1 | **缺失依赖，数据管线根本跑不起来** | `语义分割.py:4` 导入 `langchain_text_splitters`，但 `requirements.txt` 未声明 | 新环境 `pip install -r requirements.txt` 后跑数据脚本直接 `ModuleNotFoundError`。这是真 bug。 |
| P0-2 | **`bare except` + 断点续传逻辑有隐患** | `chromadb创建.py:74` `except:` 裸异常 | 吞掉一切异常（包括 `collection.count()` 的真实错误），且 `existing_count` 比较可能误跳过新数据。应捕获具体异常。 |
| P0-3 | **同一个类被复制成两份** | `agent3.py:30` 与 `chromadb创建.py:24` 都有 `DashScopeEmbeddingFunction` | 两份实现会漂移（比如一处改了重试策略，另一处不知道）。应抽到共享模块。 |

### 🟠 P1 — 可维护性 / 代码质量（团队能力提升的核心抓手）

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| P1-1 | **Agent 之间没有类型契约** | 所有 `agent/*.py` 的入口都是 `state: dict -> dict`，但 `main_graph` 已定义 `AgentState` TypedDict 却没人用 | 让每个 Agent 函数签名改为 `def run_xxx(state: AgentState) -> AgentState`。这是当前最大的可维护性风险：没人能在编译期知道 state 有哪些 key。 |
| P1-2 | **包结构靠 `sys.path.append` 撑着** | `agent1.py:5` / `agent2.py:6` / `agent4.py:5` 每个文件都 `sys.path.append(...parent)` | 说明没有正式 package。应加 `pyproject.toml` + 可编辑安装，或至少用相对导入；`agent/__init__.py` 目前是空的，应导出公共符号。 |
| P1-3 | **中文文件名 + 硬编码绝对路径 + 魔法字符串** | `语义分割.py:7-8` `r"D:\多智能体协作\..."`、`chromadb创建.py:11-13` `COLLECTION_NAME = "collection_0424"` | 中文文件名在 git/CI/跨平台工具链上会出怪问题；绝对路径让脚本只能在你本机跑；`0424` 这种日期戳魔法串应进配置。 |
| P1-4 | **在 import 时突变全局环境变量** | `chromadb创建.py:16-19`、`agent3.py:11-15` 清空 `HTTP_PROXY/HTTPS_PROXY` | 用「全局副作用」修 SSL 问题，测试时污染环境。应改成函数参数或配置。 |
| P1-5 | **类名违反 PEP8** | `model/deepseek.py:116` `class My_model_client` | 类名应 `CamelCase` → `LLMClient` / `ModelClient`。小问题，但反映规范缺失。 |
| P1-6 | **脆弱的 LLM 输出字符串解析** | `agent2.py:19,65` `DIALOGUE_COMPLETE_MARKER = "[DIALOGUE_COMPLETE]"` 注入并解析回复 | 依赖模型恰好原样输出该标记，模型一改格式就崩。优先改用结构化输出 / function calling。 |
| P1-7 | **`kwargs` 可覆盖关键请求参数** | `model/deepseek.py:157` `request.update(kwargs)` | 调用方传入的 `kwargs` 能覆盖 `model`/`messages`/`stream`。应白名单化或显式参数。 |
| P1-8 | **未保护 `choices[0]`** | `model/deepseek.py:186`、`agent4.py:85` | 假设返回必有 choice，空响应会 `IndexError`。应加守卫。 |

### 🟡 P2 — 工程化（决定团队能不能规模化）

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| P2-1 | **零自动化测试** | `pytest.ini` 存在但无任何 `test_*.py` | `medical_safety` 是纯函数，测试成本最低、收益最高，应作为团队测试启蒙。 |
| P2-2 | **无 lint / format / pre-commit / CI** | 仅 `requirements-dev.txt` 列了 `ruff`，但无配置文件、无 hook、无流水线 | 质量门禁是「代码质量把控」的实体化。本文档附带脚手架。 |
| P2-3 | **依赖只有下界、无上界、无 lock** | `requirements.txt` 全是 `>=` | 应加 `~=`/上限或 `pip-compile` 生成 lock，保证可复现。 |
| P2-4 | **`/api/chat` 无鉴权无限流** | `api.py:95` | 医疗对外服务，至少加基础鉴权 + 限速，避免滥用。 |
| P2-5 | **日志风格不一致** | 数据脚本用 `print()` + emoji（`chromadb创建.py`/`语义分割.py`），服务用 `logging` | 统一走 `logging`，便于集中采集。 |

---

## 三、团队技术能力提升路线图（mentorship）

> 原则：**先建门禁，再改契约，后补测试，最后生产化**。门禁能拦住 80% 的低级问题，让团队把精力放在设计上。

### 阶段 1：建立质量门禁（我帮你搭好了脚手架，见附赠文件）
- `pyproject.toml`：Ruff（lint + format）规则，目标 Python 3.12。
- `.pre-commit-config.yaml`：提交前自动跑 ruff，拦住格式/命名/裸异常。
- `tests/test_medical_safety.py`：给团队一个「测试长什么样」的范式。
- **动作**：`pip install -r requirements-dev.txt` → `pre-commit install` → 之后每次 commit 自动检查。

### 阶段 2：统一类型契约与包结构（P1-1 / P1-2）
- 所有 Agent 函数签名收敛到 `AgentState`。
- 引入正式 package（`pyproject.toml` + `pip install -e .`），删掉 `sys.path.append`。
- 把 `DashScopeEmbeddingFunction` 抽到 `model/embeddings.py`（修 P0-3）。

### 阶段 3：补齐测试（从最便宜的开始）
- 优先级：`medical_safety` → `session_store` 过期逻辑 → `agent1` 意图 JSON 解析 → `语义分割` 切块。
- 目标：核心纯函数 80% 覆盖，给团队建立「改代码先想测试」的习惯。

### 阶段 4：生产化
- 结构化输出替代字符串标记（P1-6）。
- `/api/chat` 加鉴权 + 限流（P2-4）。
- 依赖 lock + CI 流水线（PR 必过 ruff + pytest + 基础 mypy）。

---

## 四、「代码质量把控」运作机制（建议）

1. **PR 必过检查**：Ruff（lint+format）+ Pytest + 基础 `mypy`。CI 卡住不过不让合。
2. **Code Review 轮值**：每周一人轮值 reviewer，重点看「是否动了共享 state 契约」「有没有加测试」。
3. **新人 onboarding**：先读 `medical_safety.py`（最短、最纯、最有医疗意义），照着写第一个测试。
4. **我作为资深开发者的角色**：定期 review 关键 PR、对 P0/P1 问题做裁决、把关架构方向。

---

## 五、附赠脚手架文件（已在本次写入工作区）
- `pyproject.toml` — Ruff 质量门禁配置
- `.pre-commit-config.yaml` — 提交前自动检查
- `tests/test_medical_safety.py` — 测试范式示例
- `requirements.txt` — 已补 `langchain-text-splitters`（修 P0-1）

> 下一步告诉我你想先从哪块入手，我可以直接带团队动手：
> A) 落地阶段 1 门禁并跑通；B) 重构类型契约（P1-1/1-2）；C) 补一批核心测试；D) 修 P0 三连击。
