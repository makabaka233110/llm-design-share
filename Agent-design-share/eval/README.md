# 实验数据

## 数据集 `eval/data/`（proposal §4 规格）

| 内容 | 数量 |
|---|---|
| 参考资料 | 200 段（167 段质量好，33 段低质量），3 个领域：computing / business / science |
| 概念族 | 120 个（40 dev / 80 test），每个领域都有 dev 和 test |
| 回答 | 240 条，每个概念族一好一坏，其中 test 160 条 |
| 历史作答 | 12 组 × 3 次（persistent 6、partial 3、corrected 3） |
| 提示偏好序列 | 12 组，12 种偏好里有 4 种不同类型 |

- **来源**：由 LLM 按教材和官方文档的常识编写，不是人工采集。正式报告时需要组员抽查事实是否准确。
- **相关性标注**：做了两轮，但都由同一个模型完成，不能算两位独立的标注者，正式实验仍需两位组员复标。
- **低质量资料**（`quality: low`）：模仿论坛面经、营销号和科普号，用词与题目高度相关，但含一处事实错误，错误记在 `flaw` 字段。`queries.jsonl` 的 `weak` 字段标出每题对应的低质量资料。
- **难负例**：相邻概念的资料，例如 TCP 握手与挥手、NPV 与 IRR、有丝分裂与减数分裂。
- **已知偏差**：有缺陷的回答普遍比好回答短 30–40 字，评估实验要留意长度带来的偏差。
- **不包括**：录音需要真人录制，不在本数据集里。

### 检索实验结果（test 80 题，`--split test`）

| 设置 | Recall@3 | nDCG@3 | weak@3 |
|---|---|---|---|
| BM25 | 0.731 | 0.657 | 0.083 |
| 向量 | 0.819 | 0.742 | 0.083 |
| hybrid | 0.819 | 0.740 | 0.087 |
| weighted，quality 反馈 1 轮 | 0.806 | **0.697** | 0.087 |
| weighted，quality 反馈 3 轮 | 0.775 | **0.594** | 0.075 |
| weighted，strict 反馈 1 轮 | 0.787 | **0.679** | 0.075 |

weighted 与 hybrid 之差按题做配对 bootstrap，nDCG@3 在 4 种设置下的 95% 置信区间都不含 0。例如 quality 1 轮为 −0.043 [−0.073, −0.016]。不加反馈时 weighted 与 hybrid 完全相同（优先级都是 2）。重建索引带来的噪声约为 ±0.008。

**结论：在这个数据集上，公式 (1) 的加权没有帮助，反而有害。** 原因有两个：

1. **打分对象是资料，不是题目。** 「有用」会让这段资料在所有题里都上升。在 dev 题里有用的资料，往往正是相邻 test 题的难负例。
2. **混合检索的分数太接近。** RRF 分数只反映排名，前几名之间差距很小，优先级 0.5 的差异（乘数约差 4%）就足以改变前 3 的顺序。

低质量资料大多只与一道题相关，dev 上的反馈碰不到 test 题的低质量资料，所以 weak@3 几乎没有下降。

这一结论受限于数据由 LLM 生成、反馈是模拟的，可作为报告讨论部分的依据。

`eval/feedback_variants.py` 比较了把反馈变成排序信号的 4 种做法，分为「新题」和「回访同一题」两个场景。结论：「没用」全局生效、「有用」只对相似题生效，可以既不伤害新题，又在回访时把 nDCG@3 提高约 0.09–0.11（两次运行的结果）。完整数字见 `迭代记录.md` 第 1 条。

## 数据格式

每个文件一行一个 JSON 对象。`split` 取 `dev` 或 `test`，同一概念族（`family`）的改写题和情境题必须放在同一个 split。

| 文件 | 字段 | 用于 |
|---|---|---|
| `passages.jsonl` | `id, domain, topic, title, text, source?, priority?, reviewed?, quality?, flaw?` | 所有实验的参考库 |
| `queries.jsonl` | `id, domain, split, question, relevant: [passage id], weak?: [低质量 passage id]` | `retrieval` |
| `cases.jsonl` | `id, family, domain, split, question, concept, answer_type: strong/flawed, answer, notes?` | `evaluator`、`scenarios`（取 strong 行的题目） |
| `hint_sequences.jsonl` | `id, target_preference, history: [{question, concept, hint, rating, comment}], later: [{id, family, question, concept}]` | `hints` |
| `histories.jsonl` | `id, family, domain?, label: persistent/partial/corrected, question, concept, attempts: [3 个回答], recurring: [...]` | `history` |
| `recordings.jsonl` | `id, domain, kind: knowledge/behavioral/case, audio（相对数据目录的路径）, transcript（人工转写）` | `asr` |

输出写入 `--out`（默认 `eval/results/`）：

- `*_runs.jsonl`：原始结果，用于错误分析。
- `*_rating.csv`：打乱顺序、隐去实验条件的评分表，两位评分者分别填 `_r1` / `_r2` 列。
- `*_rating.key.jsonl`：条目与实验条件的对应关系，评分完成前不要打开。

`retrieval` 的优先级来自学习者反馈：脚本先在 dev 查询上模拟反馈，再只在其余查询上比较 4 种检索，test 标签不参与反馈。模拟时看加权检索的前 3 条，标注为相关的记「有用」；其余资料的处理由 `--feedback-policy` 决定：`quality`（默认）只对标为低质量的资料记「没用」，`strict` 对所有不相关的资料都记「没用」。`weak@3` 是前 3 条中低质量资料所占的比例。`--feedback-rounds 0` 关闭模拟；此时若资料也没有预设 `priority`，所有优先级都是 2，加权排序与 hybrid 完全相同。

`evaluator` 的盲评子集在运行前由 `balanced_subset()` 按（领域 × 强/弱回答）轮流抽取 40 例，只依赖题目元数据、不看模型输出，抽到的编号写入 `evaluator_subset.txt`。正式实验时把这个文件提交到仓库，之后用 `--subset-file` 固定。

`stats` 子命令计算评分者一致性（Cohen's κ），以及以概念族为单位、10000 次重采样的配对 bootstrap 95% 置信区间。

每个实验都使用独立的临时数据目录，因此测试答案、标签和生成的评估不会进入应用的参考库。

每个实验还会写出 `usage.json`：调用次数、失败率、token、平均延迟和费用（费用需要在 `.env` 里填 `LLM_PRICE_IN/OUT`）。

## 标注指南

**通用规则**

- 两位评分者独立评分，分别只填自己的 `_r1` 或 `_r2` 列，评完之前不讨论、不打开 `*.key.jsonl`。
- 先用 dev split 的 10 条练习，对齐理解后再评 test split。
- 跑完 `stats` 拿到一致性（κ）之后再讨论分歧，最终分歧在报告里写明处理方式。
- 1–5 分的锚点：1 = 完全没做到，3 = 做到一半或有明显问题，5 = 完全做到且没有问题。

**数据准备**

- `queries.jsonl` 的 `relevant`：一段资料只要能直接回答这个问题，或提供回答必需的事实，就算相关；只是同一主题、不能帮助回答的不算。
- `cases.jsonl`：`strong` 回答要覆盖题目的主要要点且没有错误；`flawed` 回答要包含至少一处可以由参考资料证伪的错误，或漏掉一个关键要点，并在 `notes` 里写明是哪一处。
- `histories.jsonl`：`persistent` 表示同一误解在 3 次回答里都出现；`partial` 表示有所改正但仍残留；`corrected` 表示第 3 次已经完全改正。`recurring` 填误解的简短描述。
- `recordings.jsonl` 的 `transcript`：逐字转写，保留口误和重复，不加标点也可以（计算 CER 时会去掉标点和空格）。

**各评分表的列**

| 表 | 列 | 含义 |
|---|---|---|
| evaluator | `correctness` | 反馈里指出的问题是否真的是问题（1–5）。`reference` 列是同一组参考资料，两种条件相同，供你核对事实 |
| | `usefulness` | 学习者看了能不能知道下一版怎么改（1–5） |
| | `human_score` | 你自己按 rubric（正确性、覆盖度、推理、清晰度的平均）给这份回答打的分（1–5）。表里不显示模型分，避免被锚定；用于计算模型分与人工分的误差 |
| evaluator_citations | `citation_support` | 这条反馈引用的资料是否支持它（1–5）。只有「有证据」条件会引用，所以这张表无法对条件盲评 |
| hints | `fits_preference` | 是否符合 `target_preference` 描述的偏好（1–5） |
| | `too_direct` / `too_vague` | 是否直接泄露答案 / 是否空泛到没有方向（0 或 1） |
| | `useful` / `factually_correct` | 是否有帮助（1–5）/ 内容是否正确（0 或 1） |
| history | `recurring_identified` | 若历史中确实有反复出现的误解，反馈是否点了出来（0 或 1；没有时留空） |
| | `false_recurring` | 是否把已改正的问题说成仍然存在（0 或 1） |
| | `suggestion_relevance` | 修改建议是否针对这个学习者的历史问题，而不是泛泛而谈（1–5） |
| scenarios | `concept_alignment` | 是否仍然考查原题的核心概念（1–5） |
| | `answerability` | 给出的信息是否足以作答（1–5） |
| | `contextual_change` | 情境或约束是否真的变了，而不只是换了说法（1–5） |
| | `difficulty` | 相对原题：1 = 简单很多，3 = 相当，5 = 难很多 |
| | `reference_support` | 评分要点能否由参考库支持（1–5） |
| asr | `faithful` | 总结是否忠实于人工转写（1–5） |
| | `unsupported_claims` | 总结或不足里，转写中没有依据的说法有几条（计数） |
| | `missed_points` | 转写中的重要要点被总结漏掉了几条（计数） |
| | `weakness_supported` | 列出的不足在转写里是否有依据（1–5） |
| cards | `evidence_support` | 答案是否被引用的资料支持：1 = 不支持，3 = 部分支持，5 = 完全支持；没有引用时按 1 |
| | `concept_coverage` | 卡片是否考查了该主题的核心概念，而不是边角细节（1–5） |
| | `factually_correct` | 答案是否正确（0 或 1） |
