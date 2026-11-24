# 实验数据格式

每个文件一行一个 JSON 对象。`split` 取 `dev` 或 `test`，同一概念族（`family`）的改写题和情境题必须放在同一个 split。

| 文件 | 字段 | 用于 |
|---|---|---|
| `passages.jsonl` | `id, domain, topic, title, text, priority?, reviewed?` | 所有实验的参考库 |
| `queries.jsonl` | `id, domain, split, question, relevant: [passage id]` | `retrieval` |
| `cases.jsonl` | `id, family, domain, split, question, concept, answer_type: strong/flawed, answer` | `evaluator`、`scenarios`（取 strong 行的题目） |
| `hint_sequences.jsonl` | `id, target_preference, history: [{question, concept, hint, rating, comment}], later: [{id, family, question, concept}]` | `hints` |
| `histories.jsonl` | `id, family, label: persistent/partial/corrected, question, concept, attempts: [3 个回答], recurring: [...]` | `history` |

输出写入 `--out`（默认 `eval/results/`）：

- `*_runs.jsonl`：原始结果，用于错误分析。
- `*_rating.csv`：打乱顺序、隐去实验条件的评分表，两位评分者分别填 `_r1` / `_r2` 列。
- `*_rating.key.jsonl`：条目与实验条件的对应关系，评分完成前不要打开。

`stats` 子命令计算评分者一致性（Cohen's κ），以及以概念族为单位、10000 次重采样的配对 bootstrap 95% 置信区间。

每个实验都使用独立的临时数据目录，因此测试答案、标签和生成的评估不会进入应用的参考库。
