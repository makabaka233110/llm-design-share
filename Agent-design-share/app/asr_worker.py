"""SenseVoice in its own process.

torch (SenseVoice) segfaults when loaded into the same process as the app's
onnxruntime + Milvus Lite (measured: exit 139 in-process, works standalone),
so the server talks to this worker over stdin/stdout: one audio path in, one JSON line out.
"""

import json
import re
import sys

out, sys.stdout = sys.stdout, sys.stderr  # keep library logging off the protocol channel

from funasr import AutoModel  # noqa: E402

model = AutoModel(model="iic/SenseVoiceSmall", vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
                  vad_kwargs={"max_single_segment_time": 30000}, trust_remote_code=True,
                  disable_update=True, device="cpu")


def reply(obj):
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    out.flush()


reply({"ready": True})
for line in sys.stdin:
    try:
        res = model.generate(input=line.strip(), language="auto", use_itn=True, batch_size_s=60, merge_vad=True)
        reply({"text": re.sub(r"<\|[^|]*\|>", "", "".join(r.get("text", "") for r in res)).strip()})
    except Exception as e:
        reply({"error": str(e)})
