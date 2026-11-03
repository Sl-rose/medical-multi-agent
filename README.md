# 医疗多智能体问诊助手

本项目是一个面向临床诊疗指南的多 Agent 医疗问答原型。系统通过多轮问诊收集症状信息，再结合 ChromaDB 向量检索和 Neo4j 医学知识图谱，生成参考性回答。

> 注意：本项目输出仅用于医学知识参考和问诊辅助，不能替代医生诊断、处方或急诊处置。

## 功能概览

- 多轮问诊：逐步收集症状位置、持续时间、发热等信息。
- 意图识别：区分健康咨询、报告解读、用药指导、挂号导诊、闲聊等意图。
- 知识检索：同时检索 ChromaDB 指南切片和 Neo4j 结构化医学图谱。
- 回答生成：整合问诊摘要、图谱事实和指南片段生成最终回复。
- Web 接口：FastAPI 后端 + 静态聊天页面。

## 文件说明

运行服务时会用到这些文件：

| 文件 | 作用 |
| --- | --- |
| `api.py` | FastAPI 入口，提供聊天、会话、历史和健康检查，并托管网页。 |
| `main_graph.py` | 用 LangGraph 把四个智能体串成一轮问诊。 |
| `agent/__init__.py` | 智能体包说明。四个智能体各自独立被工作流调用。 |
| `agent/agent1.py` | 识别意图，并准备 Neo4j 实体词和向量检索句。 |
| `agent/agent2.py` | 多轮问诊，一次只追问一个缺失信息；急症时直接提示急救。 |
| `agent/agent3.py` | 并发检索 ChromaDB 指南切片和 Neo4j 图谱。 |
| `agent/agent4.py` | 综合问诊摘要和检索结果生成回答，并附来源与风险提示。 |
| `model/deepseek.py` | 调用 DeepSeek 的客户端，包含超时、重试和配置校验。 |
| `session_store.py` | 保存当前会话，并缓存首轮即完成的回答。支持内存和 Redis。 |
| `chat_history.py` | 把会话标题和每轮消息写入 MySQL，供左侧历史列表使用。 |
| `medical_safety.py` | 急症关键词、急救提示、免责声明和禁止开药的约束。 |
| `logging_config.py` | 按环境变量设置日志等级，可选 JSON 行日志。 |
| `static/index.html` | 问诊页面：左侧历史，右侧对话。 |
| `requirements.txt` | 运行依赖。 |
| `requirements-dev.txt` | 测试和代码检查依赖。 |
| `pyproject.toml` | 项目元数据，以及 Ruff、mypy 规则。 |
| `pytest.ini` | pytest 的测试收集配置。 |
| `tests/test_medical_safety.py` | 医疗安全判断的示例单元测试。 |
| `.env.example` | 环境变量样例。复制为 `.env` 后填写本机密钥。 |
| `.gitignore` | 排除密钥、缓存、向量库和指南原文。 |
| `.editorconfig` | 统一 UTF-8、换行和缩进。 |
| `.pre-commit-config.yaml` | 提交前的格式和体积检查。 |

构建知识库时单独运行这些脚本，它们不参与在线问诊：

| 文件 | 作用 |
| --- | --- |
| `split.py` | 把超过页数限制的 PDF 切成小文件。 |
| `pdf_to_markdown.py` | 把 PDF 上传到 MinerU，申请转成 Markdown。 |
| `download_markdown.py` | 按批次号下载转换结果并解压。 |
| `test.py` | 从已下载压缩包中按书名抽出 Markdown。 |
| `语义分割.py` | 按标题和段落把指南切成 `rag_chunks.json`。 |
| `chromadb创建.py` | 把切片写入本地 ChromaDB。 |
| `neo4j导入.py` | 把 `medical.json` 的疾病记录导入 Neo4j。 |
| `inspect_neo4j.py` | 查看图谱里的标签、关系和字段样例。 |
| `CODE_REVIEW_AND_ROADMAP.md` | 代码质量评审和后续改进清单。 |

以下内容只留在本机，不进入 Git 仓库：`.env`、`chromadb/`、`guidelines_md/`、`临床诊疗指南/`、`medical.json`、`rag_chunks.json`。

## 环境准备

建议使用 Python 3.12 或更高版本。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

安装开发检查工具：

```bash
pip install -r requirements-dev.txt
```

复制环境变量样例并填写真实配置：

```bash
copy .env.example .env
```

必填变量：

- `DEEPSEEK_API_KEY`：DeepSeek/OpenAI 兼容接口密钥。
- `BASE_URL`：大模型接口地址，例如 `https://api.deepseek.com`。
- `MODEL_NAME`：模型名称。
- `LLM_TIMEOUT_SECONDS`：大模型请求超时时间，默认 60 秒。
- `LLM_MAX_RETRIES`：大模型请求失败后的最大尝试次数，默认 3 次。
- `LLM_RETRY_BACKOFF_SECONDS`：重试退避基数，默认 1.5 秒。
- `LLM_TEMPERATURE`：可选的大模型温度参数，留空则不传。
- `LLM_MAX_TOKENS`：可选的最大输出 token 数，留空则不传。
- `LOG_LEVEL`：日志等级，默认 `INFO`，排障时可设为 `DEBUG`。
- `LOG_FORMAT`：日志格式，默认包含时间、级别和 logger 名称；设置为 `json` 时输出 JSON 行日志。
- `DASHSCOPE_API_KEY`：DashScope 文本向量模型密钥。
- `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`：Neo4j 连接配置。
- `CHROMA_PATH`：ChromaDB 本地目录，留空时默认使用项目下的 `chromadb/`。
- `SESSION_STORE`：会话存储类型，开发可用 `memory`，生产建议用 `redis`。
- `SESSION_TTL_SECONDS`：会话过期时间，默认 7200 秒。
- `REDIS_URL`：Redis 连接地址，例如 `redis://localhost:6379/0`。
- `REDIS_KEY_PREFIX`：Redis 会话 key 前缀。
- `HISTORY_DB_URL`：历史对话 MySQL 连接地址。
- `ANSWER_CACHE_ENABLED`：是否启用最终答案缓存，默认启用。
- `ANSWER_CACHE_MIN_QUERY_LENGTH`：进入答案缓存的最短问题长度，默认 12 个字符。
- `MINERU_TOKEN`：仅数据构建脚本使用的 MinerU 访问令牌。在线问诊不需要它。

## 启动服务

确保 Neo4j 服务已启动，且 `chromadb/` 中已有向量集合。

```bash
python api.py
```

如果 Windows PowerShell 输出 emoji 日志时报编码错误，可以先设置：

```powershell
$env:PYTHONIOENCODING="utf-8"
python api.py
```

默认访问：

- Web 页面：http://127.0.0.1:8088
- 健康检查：http://127.0.0.1:8088/api/health，会返回会话数、会话存储类型、检索组件初始化状态和 LLM 配置状态。

## Redis 会话存储

本项目默认使用内存会话存储，适合本地开发。生产环境建议使用 Redis：

```env
SESSION_STORE=redis
SESSION_TTL_SECONDS=7200
REDIS_URL=redis://localhost:6379/0
REDIS_KEY_PREFIX=medical-chat:session
```

默认情况下，如果 Redis 暂时不可用，服务会退回内存存储，并在 `/api/health` 的 `session_store.startup_error` 中暴露错误原因。生产环境如果希望 Redis 不可用时直接启动失败，可以设置：

```env
SESSION_STORE_FALLBACK_TO_MEMORY=false
```

### 答案缓存

当一次问诊在首轮就完成并生成最终回答后，系统会把“原始问题 -> 最终回答”缓存到会话存储中，过期时间与 `SESSION_TTL_SECONDS` 一致。新会话第一轮输入同样的问题时，如果命中缓存，会直接返回之前的最终回答。

多轮问诊产生的答案不会用首轮问题做直接缓存，避免“首轮信息不完整”导致后续误命中。

Redis key 形态类似：

```text
medical-chat:answer:<sha256>
```

为了避免“肚子疼”这类过短问题误命中，默认只有长度不少于 12 个字符的问题才会进入缓存。可以通过 `.env` 调整：

```env
ANSWER_CACHE_ENABLED=true
ANSWER_CACHE_MIN_QUERY_LENGTH=12
```

## MySQL 历史对话

Redis 仍用于当前会话状态和短期答案缓存；长期历史对话存入 MySQL。先创建数据库：

```sql
CREATE DATABASE medical_chat
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

然后在 `.env` 配置：

```env
HISTORY_DB_URL=mysql+pymysql://root:你的密码@127.0.0.1:3306/medical_chat?charset=utf8mb4
```

应用启动时会自动创建两张表：

- `chat_sessions`：会话标题、完成状态、创建/更新时间。
- `chat_messages`：每轮用户和助手消息。

左侧历史列表来自 MySQL，因此 Redis TTL 过期不会影响历史记录。

## 数据构建流程

当前数据处理脚本仍偏向本地一次性任务，推荐按下面顺序执行：

1. `split.py`：拆分超页数 PDF。
2. `pdf_to_markdown.py`：上传 PDF 并申请 Markdown 转换。
3. `download_markdown.py` 或 `test.py`：下载/提取 Markdown。
4. `语义分割.py`：生成 `rag_chunks.json`。
5. `chromadb创建.py`：将切片写入 ChromaDB。
6. `neo4j导入.py`：将 `medical.json` 导入 Neo4j。

MinerU 令牌从 `MINERU_TOKEN` 读取，Neo4j 密码从 `NEO4J_PASSWORD` 读取。脚本里的本地目录仍是一次性路径，后续建议改成命令行参数。

## 开发检查

快速检查 Python 文件是否可编译：

```bash
python -m py_compile api.py main_graph.py model\deepseek.py agent\agent1.py agent\agent2.py agent\agent3.py agent\agent4.py
```

如果后续补充了 pytest 测试，可以运行：

```bash
pytest
```

## 安全与提交建议

- 不要提交 `.env`、API Key、Neo4j 密码等敏感信息。
- 不要提交大型生成物，如 PDF、zip、ChromaDB 数据库、大型 JSON。
- 建议将数据文件和代码仓库分离管理。
- 医疗回答需要始终保留风险提示和就医建议边界。
