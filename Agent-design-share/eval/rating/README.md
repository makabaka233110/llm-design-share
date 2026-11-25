# 人工评分包

proposal §4 中所有要求人工完成的评测，以及对应的表。表都是由 DeepSeek `deepseek-flash` 在 2026-11-24 的真实运行生成的（相关性表和历史标签表由 `eval/run.py annotate` 生成）。各列含义见 `eval/README.md`「标注指南」。

| # | proposal 原文 | 表 | 几个人 | 行数 × 列数 | 每人大约 |
|---|---|---|---|---|---|
| 1 | Two annotators will establish passage relevance | `relevance_rating.csv`（80 道 test 题，4 种检索方式前 3 名合并 + 标注的相关资料） | **2** | 433 × 1（0/1） | 40 分钟 |
| 2 | blinded evaluation by two raters for correctness, usefulness, citation support, and model-versus-human score error（预先指定的 40 例平衡子集，见 `evaluator_subset.txt`） | `evaluator_rating.csv`（40 例 × 有证据/无证据） | **2** | 80 × 3 | 60 分钟 |
| | （同上：citation support） | `evaluator_citations.csv` | **2** | 267 × 1 | 40 分钟 |
| 3 | Two annotators will establish change labels（12 组历史作答） | `history_labels.csv` | **2** | 12 × 1 | 10 分钟 |
| 4 | compared for recurring-error detection, false flags for resolved gaps, and suggestion relevance | `history_rating.csv` | 1–2 | 24 × 3 | 15 分钟 |
| 5 | human checks will prevent factually incorrect hints from counting as personalization successes；按偏好、太直接 / 太模糊、有用程度评估 | `hints_rating.csv` | 1–2 | 48 × 5 | 40 分钟 |
| 6 | two variants for each of 20 held-out questions … rated for concept alignment, answerability, contextual change, difficulty, and reference support | `scenarios_rating.csv` | 1–2 | 37 × 5 | 30 分钟 |
| 7 | 12 short recordings with human transcripts to assess transcription errors and summary faithfulness | `asr_rating.csv`（转写错误率已自动算出，只评总结） | 1–2 | 12 × 4 | 10 分钟 |
| 8 | Twenty flashcards will be reviewed for evidence support and concept coverage | `cards_rating.csv` | 1–2 | 20 × 3 | 15 分钟 |
| 9 | （可选）12–20 人学习效果试点，前测与 7 天后测 | — | 参与者 | — | 未做 |

proposal 明确写了「两人」的是第 1、2、3 项；其余只写了「评」，一人评也说得过去，两人评可以多报一个一致性。另外报告前需要组员抽查 `eval/data` 里资料和标准答案的事实是否正确（proposal：数据选择依赖「可靠资料和评估者的专业知识」）。

## 怎么做
1. 两位评分者各拿一份表，只填自己的 `_r1` 或 `_r2` 列，评完之前不讨论。
2. **不要打开** `*.key.jsonl`（答案键：实验条件、模型分数、模型写的标签）。答案键不在仓库里，由不评分的组员保管，评完后放回本目录。
3. 评完运行，例如：
   ```bash
   .venv/bin/python eval/run.py stats eval/rating/evaluator_rating.csv --metric usefulness --a none --b weighted
   .venv/bin/python eval/run.py stats eval/rating/relevance_rating.csv     # 两人一致性 + 与模型标注的一致性
   ```
