"""Builds eval/data_asr: 12 short spoken answers for the speech check (proposal §4: "12 short recordings with
human transcripts"). The recordings are synthesised with macOS `say` (voice Tingting), so the reference
transcript is exactly the text that was spoken. Synthetic speech is cleaner than a real learner (no fillers,
accent or noise), so the transcription error rate measured on it is optimistic.

  python eval/data_asr/build.py          # macOS only; writes rec00.wav .. rec11.wav and recordings.jsonl
  .venv/bin/python eval/run.py asr --data eval/data_asr
"""
import json
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent
SPEECH = [  # (domain, kind, text)
    ("computing", "knowledge", "Redis 有两种持久化方式，RDB 快照和 AOF 日志。RDB 恢复快，但是可能丢掉最后一次快照之后的数据。"),
    ("computing", "knowledge", "TCP 需要三次握手，是为了让双方确认初始序列号，同时防止历史连接被误认为新连接。"),
    ("economics", "knowledge", "机会成本是做出选择时放弃的次优选项的价值，不是已经花掉的钱。"),
    ("economics", "knowledge", "沉没成本已经发生，无法收回，所以理性决策时不应该考虑它。"),
    ("behavioral", "behavioral", "我上一个项目里和产品经理有分歧，我先把双方的目标写下来，再用数据说明方案的影响，最后达成一致。"),
    ("computing", "knowledge", "如果系统每秒写入一万次，我会选择 AOF，并把同步策略设为每秒一次，这样宕机最多丢一秒的数据。"),
    ("computing", "knowledge", "数据库索引一般用 B 加树，因为它的高度低，范围查询也很高效。"),
    ("economics", "knowledge", "边际成本是多生产一个单位带来的额外成本，企业通常在边际收益等于边际成本时达到利润最大。"),
    ("behavioral", "behavioral", "我遇到过一次线上故障，第一步是止损回滚，然后定位原因，最后写复盘文档，补上监控。"),
    ("computing", "knowledge", "缓存穿透是查询不存在的数据，请求直接打到数据库，可以用布隆过滤器或者缓存空值来解决。"),
    ("economics", "knowledge", "需求价格弹性衡量的是价格变化百分之一时，需求量变化的百分比。"),
    ("behavioral", "behavioral", "当团队优先级冲突时，我会先和负责人对齐目标，然后按影响和紧急程度排序，并及时同步给大家。"),
]


def main():
    rows = []
    for i, (domain, kind, text) in enumerate(SPEECH):
        wav, aiff = OUT / f"rec{i:02d}.wav", OUT / f"rec{i:02d}.aiff"
        subprocess.run(["say", "-v", "Tingting", "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)], check=True)
        aiff.unlink()
        rows.append({"id": f"r{i:02d}", "domain": domain, "kind": kind, "audio": wav.name, "transcript": text,
                     "source": "synthetic: macOS say -v Tingting"})
    (OUT / "recordings.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(f"{len(rows)} recordings")


if __name__ == "__main__":
    main()
