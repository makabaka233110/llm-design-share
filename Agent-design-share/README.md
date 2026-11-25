# 面壁 Mianbi — 有证据的面试训练与持续学习记录

第 68 组项目代码。实现 proposal 中的四个基础模块（知识库与反馈排序、模拟面试、语音复盘、闪卡）和三个扩展（个性化提示、费曼讲解与版本历史、关联情境题），以及第 4 节实验所需的脚本。

## 启动

需要 macOS / Linux，Python 3.12+ 或 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/makabaka233110/llm-design-share.git
cd llm-design-share/Agent-design-share
bash start.sh          # 首次运行会生成 .env；填好 LLM 配置后重启即可启用 AI 功能
```

打开 http://127.0.0.1:8000 。知识库默认是空的（学习者放自己审核过的资料）。演示时可以在另一个终端运行 `python3 eval/demo_kb.py`，导入数据集中 167 段正确的资料（三个领域，已审核；故意写错的 33 段只用于实验，不导入）。知识库检索、闪卡复习和语音转写在本地运行；评估、提示、出题和复盘会把相关文本发送到 `.env` 中配置的模型服务。右上角可切换简体中文 / 繁體中文 / English（只切界面文案，AI 生成的内容仍是模型回答时用的语言）。

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
| `app/calc.py` | 程序核算：回答和评语里的「算式 = 结果」由程序计算，模型只判断方法 |
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
| 评估器取重排后前 3 条已审核资料，并逐条核对回答中的论断 | `retrieval.evidence()`：题目 + 概念检索取前 3 条；回答按句拆成论断，每句从检索前 3 名里取语义最接近的 1 条，标注「用于核对」哪句话。相似度低于门槛的资料不当证据 |
| 检索笔记、面试问题与审核资料 | 已审核资料是评分证据；题库里语义最近的问题（bge-m3）作为「相关问题」传给评估器和详情页，只作参考，不作为评分依据 |
| （新增）计算由程序完成 | 回答中的算式先由 `calc.py` 计算，结果作为事实交给评估器；评语里模型写的数字也由程序复核。计算题测试集上，算术错误的漏判从 9/18 降到 0/18 |
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

## proposal 之外新增的

每一项都来自实验中发现的 bad case 或实际运行的需要，详见 [ITERATION_LOG.md](ITERATION_LOG.md)。

| 新增 | 由来 |
|---|---|
| 计算交给程序（`app/calc.py`）：回答和评语里的「算式 = 结果」由程序计算，模型只判断方法 | 正确的计算被判错、错误的计算被判对；计算题测试集上，算术错误的漏判从 9/18 降到 0/18 |
| 证据相关性门槛：无关资料不当证据，专业知识题没有相关资料时返回「无法确定」 | SWOT 题被拿 TIME_WAIT 资料核对 |
| 总分规则：正确性 ≤ 2 时总分不超过正确性 | 答错核心概念仍有 3.5 分 |
| 反馈改进实验（`eval/feedback_variants.py`）：反馈只作用于相似的题 | 公式 (1) 让新题检索变差。目前只做了离线验证，应用仍按 proposal 使用公式 (1) |
| 计算题测试集 `eval/data_calc`（数字由程序核验） | 验证程序核算 |
| BM25 中文停用词；分词配置变化时自动重建索引 | 问碳-14 搜出《三次握手》 |
| 评分标准变化时，版本号自动带哈希值 | review 发现 |
| 详情页「题库中的相关问题」、薄弱点「去练习」 | 落实 proposal 中「检索面试问题」和「薄弱点连到后续练习」 |
| 可点击的架构图页面 | 演示用 |
| 任意 OpenAI 兼容模型 + 额外请求参数（如关闭 DeepSeek 的思考） | 实际运行需要 |

## §4 实验完成度

| proposal §4 | 状态 |
|---|---|
| 约 200 段资料、120 道题、3 个领域、40 dev / 80 test | ✅ `eval/data`（由 LLM 编写，需要组员抽查事实） |
| 4 种检索比较 Recall@3、nDCG@3、延迟 | ✅ |
| 160 例回答：有证据 vs 无证据（真实模型 DeepSeek flash） | ✅ 自动指标已出 |
| 提示 12 组、历史 12 组 × 3、情境题 20 × 2、闪卡 20 张 | ✅ 已生成，自动指标已出 |
| 语音 12 段 + 参考转写稿 + 转写错误率 + 复盘总结 | ✅ `eval/data_asr`（`build.py` 用 macOS `say` 合成）。proposal 要求「12 段短录音和人工转写稿」，没有要求必须是真人说话；参考稿就是合成的输入文本。合成语音比真人干净，错误率 0.039 偏乐观 |
| 用量、成本、延迟、失败率 | ✅ |
| 功能验收、端到端流程 | ✅ 21 个单元测试 + 12 条浏览器流程 |
| 人工部分（proposal 原文要求）：两名标注者标资料相关性、两名评分者盲评 40 例、两名标注者标历史作答的变化、人工检查提示事实是否正确 | ⚠️ **由两名 LLM 评分员（Claude Sonnet 5.5，独立、盲评）代替人工完成**，结果见 [`eval/rating/llm/README.md`](eval/rating/llm/README.md)。主要结论：有证据时反馈正确性 +0.28 [+0.08, +0.51]；相关性标签 κ = 0.96。给真人用的空白表仍在 [`eval/rating/`](eval/rating/README.md) |
| 学习效果试点（12–20 人） | 未做（proposal 中为可选项） |

## 和上一版相比修掉的问题

完整的踩坑记录和实验发现（现象、原因、处理、证据）见 [ITERATION_LOG.md](ITERATION_LOG.md)，新发现请追加在那里。

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
.venv/bin/python -m pytest -q        # 21 个测试：真实检索 + 脚本化的假 LLM，以及实验脚本的统计函数
BASE=http://127.0.0.1:8000/ python tests/ui_flows.py   # 用真实 Chrome 点完 12 条主要流程（需要 pip install playwright）
```

## 与 proposal 不同的地方

（proposal 只要求「用户记录相互隔离、可删除个人数据」，没有要求登录。本项目按 `X-User` 隔离数据、可一键删除，没有做认证；多人共用部署时需要在前面加一层登录。）

- **行为题和案例题在没有资料时也会评分**：这两类题考查结构和取舍，通常没有可引用的事实依据，所以不强制要求证据；专业知识题没有相关的已审核资料时返回「无法确定」。「相关」用 bge-m3 相似度门槛判断（题目 0.50、逐句核对 0.55，在 dev 上选定，见 `eval/claim_threshold.py`）。
- **反馈加权仍按公式 (1)（与 proposal 一致，说明原因）**：proposal 把公式 (1) 定为「固定规则」，并要求与不加权基线比较，看加权是否有帮助。实验结论是它让新题变差，这本身就是要报告的结果。改进做法「按相似题生效」只做了离线验证，没有替换应用里的规则，否则评测的就不是 proposal 里的系统了。见迭代记录第 1 条。
- **人工评分改由 LLM 评分员完成**：proposal 要求两名人类评分者 / 标注者。由于时间所限，由两名独立的 Claude Sonnet 5.5 评分员盲评代替；被评内容由 DeepSeek 生成，二者不同源。这样测到的「模型分与人工分的误差」实际上是两个模型之间的误差，不能代替真人判断。见 `eval/rating/llm/README.md`。
- **总分规则**：proposal 只规定了四个维度。界面上的总分是四项平均，但正确性 ≤ 2 时总分不超过正确性，避免答错核心概念、只因表达清楚就拿到 3.5 分。

## 组件来源

[Memsearch](https://github.com/zilliztech/memsearch)（索引与混合检索）、[BGE-M3](https://arxiv.org/abs/2402.03216)、[SenseVoice](https://github.com/FunAudioLLM/SenseVoice)、[jieba](https://github.com/fxsjy/jieba)；SM-2 按照 Woźniak 的原始描述实现。许可遵循各自上游。
