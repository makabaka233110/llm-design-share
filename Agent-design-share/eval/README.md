# 实验数据格式

每个文件一行一个 JSON 对象。`split` 取 `dev` 或 `test`，同一概念族（`family`）的改写题和情境题必须放在同一个 split。

| 文件 | 字段 | 用于 |
|---|---|---|
| `passages.jsonl` | `id, domain, topic, title, text, priority?, reviewed?` | 所有实验的参考库 |
| `queries.jsonl` | `id, domain, split, question, relevant: [passage id]` | `retrieval` |
| `cases.jsonl` | `id, family, domain, split, question, concept, answer_type: strong/flawed, answer, notes?` | `evaluator`、`scenarios`（取 strong 行的题目） |
| `hint_sequences.jsonl` | `id, target_preference, history: [{question, concept, hint, rating, comment}], later: [{id, family, question, concept}]` | `hints` |
| `histories.jsonl` | `id, family, domain?, label: persistent/partial/corrected, question, concept, attempts: [3 个回答], recurring: [...]` | `history` |
| `recordings.jsonl` | `id, domain, kind: knowledge/behavioral/case, audio（相对数据目录的路径）, transcript（人工转写）` | `asr` |

输出写入 `--out`（默认 `eval/results/`）：

- `*_runs.jsonl`：原始结果，用于错误分析。
- `*_rating.csv`：打乱顺序、隐去实验条件的评分表，两位评分者分别填 `_r1` / `_r2` 列。
- `*_rating.key.jsonl`：条目与实验条件的对应关系，评分完成前不要打开。

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
| evaluator | `correctness` | 反馈里指出的问题是否真的是问题（1–5） |
| | `usefulness` | 学习者看了能不能知道下一版怎么改（1–5） |
| | `citation_support` | 反馈引用的证据是否真的支持该条反馈（1–5；没有证据列时留空） |
| | `human_score` | 你自己按 rubric（正确性、覆盖度、推理、清晰度的平均）给这份回答打的分（1–5），用于计算模型分与人工分的误差 |
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
