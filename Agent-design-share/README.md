# 面壁 Mianbi — 有证据的面试训练与持续学习记录

第 68 组项目代码。实现 proposal 中的四个基础模块（知识库与反馈排序、模拟面试、语音复盘、闪卡）和三个扩展（个性化提示、费曼讲解与版本历史、关联情境题），以及第 4 节实验所需的脚本。

## 启动

需要 macOS / Linux，Python 3.12+ 或 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/makabaka233110/llm-design-share.git
cd llm-design-share/Agent-design-share
bash start.sh          # 首次运行会生成 .env；填好 LLM 配置后重启即可启用 AI 功能
```

打开 http://127.0.0.1:8000 。知识库检索、闪卡复习和语音转写在本地运行；评估、提示、出题和复盘会把相关文本发送到 `.env` 中配置的模型服务。

## 一条学习链路

```
资料（知识库，已审核）──检索──▶ 评估器 ◀── 作答（模拟面试 / 费曼讲解 / 情境题）
        ▲ 有用/没用 → 优先级          │
        │                            ▼
        │                 薄弱点（待确认 → 已确认）◀── 语音复盘
        │                     │            │
        │                 闪卡草稿 → SM-2 复习   情境题（关联原题与概念）
        └─ 只有人工审核过的资料能当证据；AI 生成内容和学习记录永不进入参考库
```

## 架构

| 文件 | 职责 |
|---|---|
| `app/db.py` | 学习记录库（一个 SQLite）：题目、作答版本、评估、提示与偏好、会话、复盘、薄弱点、闪卡、用量日志 |
| `app/retrieval.py` | 参考库：Markdown + Memsearch（bge-m3 ONNX + Milvus Lite）。四种检索模式 `bm25 / dense / hybrid / weighted`，优先级重排公式 (1) |
| `app/agent.py` | 所有 LLM 工具及其 prompt：评估、面试官、复盘、提示与偏好归纳、情境题生成与检查、闪卡生成 |
| `app/llm.py` | 唯一的模型入口：OpenAI 兼容 / Anthropic，JSON 校验 + 1 次纠错重试，记录 token 与延迟 |
| `app/srs.py` | SM-2 与固定 1/3/7 天两种调度 |
| `app/api/*.py` | HTTP 接口（按模块拆分），`X-User` 区分学习者 |
| `app/static/` | 单页前端（原生 JS，无构建步骤、无外部 CDN） |
| `eval/run.py` | 第 4 节实验脚本 |
| `app/static/architecture.html` | 分层架构图（目标 → 页面 → 一次提交 → 代码），方框可点击跳转到对应页面，适合演示 |

## proposal 对照

| proposal | 实现位置 |
|---|---|
| 资料增删改、来源 / 主题 / 版本 / 审核状态 / 优先级 | `api/knowledge.py`；修改正文时版本号加 1 并重新索引；粘贴的资料默认「未审核」，学习者勾选后才能作为评分证据 |
| `final = hybrid × (1 + 0.1 × priority)`，priority ∈ [0,5]，默认 2，有用 +0.5，没用 −1 | `retrieval.retrieve(mode="weighted")`；候选池逐步翻倍，直到池外的段落不可能进入前 k；`hybrid` 模式即不加权基线 |
| 评估器取重排后前 3 条已审核资料，并逐条核对回答中的论断 | `retrieval.evidence()`：题目 + 概念检索取前 3 条（E1–E3）；回答按句拆成论断，每句再检索 1 条（E4…），标注「用于核对」哪句话 |
| 检索笔记、面试问题与审核资料 | 已审核资料是评分证据；题库里语义最近的问题（bge-m3）作为「相关问题」传给评估器和详情页，只作参考，不作为评分依据 |
| 证据不足或输出无效时不编造分数 | `status = uncertain / unavailable`，`scores = null` |
| 1–5 分 rubric（正确性、覆盖度、推理、清晰度），反馈关联原话与证据编号 | `agent.evaluate`；引用若不在原文中、证据编号若不存在，都会被丢弃 |
| 存储 rubric 与模型版本 | `evaluations.rubric_version / model / evidence_mode / history_aware`；领域评分标准变了，rubric 版本号随之改变（`r1+<哈希>`），对比时条件不同会提示不可直接比较 |
| 模拟面试：岗位、领域、题型（专业知识 / 行为 / 案例），追问或换题，会话保存与恢复 | `api/interview.py`；最多连续追问 2 次。每个问题进入题库，标注 `origin=interview` |
| 语音：SenseVoice 本地转写 → 可编辑 → 复盘 → 保存 → 薄弱点 → 闪卡草稿 | `api/speech.py` + `api/practice.py` 中的 gaps |
| 闪卡：手动 / 生成 / 集合 / 导入导出 / 删除 / 到期队列 / 统计 / 退出队列；关联薄弱点与原题 | `api/cards.py`（`gap_id`、`question_id`、`sources`） |
| Ext 1：提示与反馈分别存储，偏好可查看 / 编辑 / 重置，按用户隔离，生成新提示时使用 | `agent.hint / update_prefs`；每条提示记录所用的偏好版本 |
| Ext 2：费曼讲解（文字或语音），每次修改是新版本，时间线 + 并排对比，参考历史作答 | `POST /api/questions/{id}/attempts`；评估条件不同时，界面提示分数不可直接比较 |
| Ext 3：情境题保留概念、改变情境，评分要点在作答前隐藏，检查概念、可答性、与父题或已有题目是否重复 | `agent.scenario`：查重范围 = 同题族 + 同概念 + 题库中语义最近的题；未通过则带原因重试 1 次 |
| Ext 3：查看同一概念在不同情境下的表现 | 题库「按概念」视图（`GET /api/concepts`，弱的概念在前）；题目详情页「同一概念的表现」 |
| 复盘发现的薄弱点关联到后续练习 | 已确认的薄弱点可「去练习」：生成一道关联的练习题（`gaps.question_id`），可继续出情境题、生成闪卡 |
| 参考库与学习记录库分离 | 参考库为 `data/kb/*.md` + Milvus，其余数据全部在 SQLite |
| 用户隔离、可删除个人数据 | 每张表都有 `user_id`；`DELETE /api/me` |
| 记录 API 用量、成本、延迟、失败率 | `llm_log` 表；`.env` 填 `LLM_PRICE_IN/OUT` 后按 token 换算费用；界面「学习记录 → 用量」，实验输出 `usage.json` |
| 记录依赖版本 | `requirements.lock`（实际测试通过的精确版本） |

## 和上一版相比修掉的问题

完整的踩坑记录和实验发现（现象、原因、处理、证据）见 [迭代记录.md](迭代记录.md)，新发现请追加在那里。

- 优先级原来从 chunk 文本里解析，只有文件头所在的那个 chunk 有这一行，其他 chunk 一律按 2。现在优先级存在 `docs` 表里，同一文件的所有 chunk 都能读到。
- 面试评估原来不经过重排，评估时也没有把题目传给模型。现在评估统一走 `evidence()`，题目、概念和评分要点都会传入。
- 面试总结、录音转写原来以优先级 4 写进知识库，下一次又被当作评分证据。现在它们写入学习记录库。
- JSON 解析失败时原来会编造 3 分，现在返回 `unavailable`。
- Milvus 默认的 `standard` 分词器不切中文，BM25 对中文查询基本没有命中。现在用 jieba 建索引。另外 Milvus Lite 返回的 BM25 距离是负数，原代码直接按它排序，顺序是反的，现已修正。
- BM25 原来不过滤虚词：「为什么」「这是」这类词在课本式资料里很少出现，IDF 反而很高，口语化的论坛面经凭虚词排到了前面。现在加了中文停用词和标点过滤，在 `eval/data` 的 80 道 test 题上，BM25 的 Recall@3 从 0.656 提到 0.731。分词配置变化时，索引会自动重建。
- hybrid 和 weighted 原来使用的候选池大小不同（RRF 的融合结果取决于候选数），所以两者的差别不只是优先级。现在两者共用 40 条候选，不加反馈时结果完全相同。
- Memsearch 原来使用全局默认库 `~/.memsearch/milvus.db`，现在改为项目内的 `data/milvus.db`。
- 前端原来把 LLM 输出直接插入 HTML，存在 XSS 风险。现在所有动态内容都会转义。

## 实验（proposal §4）

| 子命令 | proposal §4 | 需要 LLM | 输出 |
|---|---|---|---|
| `retrieval` | 4 种检索的 Recall@3、nDCG@3、延迟，按领域；优先级由 dev 查询上模拟的有用 / 没用反馈产生 | 否 | 直接打印 |
| `evaluator` | 有证据 vs 无证据；强 / 弱回答的分差，按领域；预先指定的 40 例平衡盲评子集（表中不显示模型分和条件） | 是 | `evaluator_rating.csv`、`evaluator_citations.csv` |
| `hints` | 通用提示 vs 偏好条件提示 | 是 | `hints_rating.csv` |
| `history` | 只看本次 vs 参考历史；反复错误识别、建议相关性 | 是 | `history_rating.csv` |
| `scenarios` | 每题 2 个情境变体 + 自动检查 | 是 | `scenarios_rating.csv` |
| `asr` | SenseVoice 转写错误率（CER）+ 复盘总结忠实度 | 总结部分需要 | `asr_rating.csv` |
| `cards` | 20 张生成闪卡的证据支持与概念覆盖 | 是 | `cards_rating.csv` |
| `stats` | Cohen's κ、模型分与人工分的误差、按条件 / 领域的均值、概念族配对 bootstrap 95% CI | 否 | 直接打印 |

```bash
.venv/bin/python eval/run.py retrieval --data eval/sample
.venv/bin/python eval/run.py evaluator --data <数据目录> --split test
.venv/bin/python eval/run.py stats eval/results/evaluator_rating.csv --metric usefulness --a none --b weighted
```

数据集、检索实验结果、真实模型（DeepSeek flash）运行结果、数据格式和标注指南见 `eval/README.md`。`eval/data/` 是按 proposal §4 规格构建的数据集（200 段资料、120 个概念族）；`eval/sample/` 只是演示格式的小样例。

## 测试

```bash
.venv/bin/python -m pytest -q        # 14 个测试：真实检索 + 脚本化的假 LLM，以及实验脚本的统计函数
BASE=http://127.0.0.1:8000/ python tests/ui_flows.py   # 用真实 Chrome 点完 12 条主要流程（需要 pip install playwright）
```

## 与 proposal 不同的地方

- **行为题和案例题在没有资料时也会评分**：这两类题考查结构和取舍，通常没有可引用的事实依据，所以不强制要求证据；专业知识题没有已审核资料时返回「无法确定」。资料是否足以判断，由评估器按 prompt 规则判断，没有设相似度阈值。
- **用户隔离没有登录**：数据按 `X-User` 分开存储，可一键删除，但没有密码。proposal 的场景是个人在本机使用，所以没加认证；如果要部署给多人共用，需要在前面加一层登录。

## 组件来源

[Memsearch](https://github.com/zilliztech/memsearch)（索引与混合检索）、[BGE-M3](https://arxiv.org/abs/2402.03216)、[SenseVoice](https://github.com/FunAudioLLM/SenseVoice)、[jieba](https://github.com/fxsjy/jieba)；SM-2 按照 Woźniak 的原始描述实现。许可遵循各自上游。
