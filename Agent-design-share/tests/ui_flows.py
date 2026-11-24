"""Drive real Chrome through every main flow and report errors.

  pip install playwright            # uses your installed Chrome, no browser download
  BASE=http://127.0.0.1:8000/ HEADED=1 SLOW=400 python tests/ui_flows.py

Each step = a user action + the element that must appear afterwards.
Failure = the element never appears, a console error, an uncaught JS exception,
or any /api/ response >= 400. Note: it adds data to whatever server you point it at.
"""
import os
from playwright.sync_api import sync_playwright
B = os.getenv("BASE", "http://127.0.0.1:8000/")
errs = []
def step(name, fn):
    try: fn(); print("ok  ", name)
    except Exception as e: errs.append(f"{name}: {e}"); print("FAIL", name, str(e)[:200])
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=not os.getenv("HEADED"), slow_mo=int(os.getenv("SLOW", "0")))
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("console", lambda m: m.type == "error" and errs.append("console: " + m.text))
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
    pg.on("response", lambda r: r.status >= 400 and "/api/" in r.url and errs.append(f"http {r.status} {r.url}"))
    pg.goto(B + "#kb"); pg.wait_for_selector("#kb-list .item")
    def kb_add():
        pg.click("text=+ 添加资料"); pg.fill("#d-title", "CAP 定理"); pg.fill("#d-topic", "分布式")
        pg.fill("#d-body", "CAP 定理指出网络分区时无法同时保证一致性和可用性。"); pg.click("#kb-editor button.primary")
        pg.wait_for_selector("text=CAP 定理", timeout=60000)
    step("kb add doc", kb_add)
    def kb_search():
        pg.fill("#kb-q", "Redis 宕机丢多少数据"); pg.click('button:text-is("检索")'); pg.wait_for_selector("#kb-results .evidence")
        for m in ("BM25", "向量", "混合"):
            pg.click(f"#kb-mode >> text={m}"); pg.wait_for_timeout(600)
        pg.click("#kb-results .evidence >> nth=0 >> text=没用"); pg.wait_for_timeout(800)
    step("kb search 4 modes + feedback", kb_search)
    def kb_edit():
        pg.click("#kb-list .item >> nth=0"); pg.wait_for_selector("#d-body"); pg.click("#kb-editor button.primary"); pg.wait_for_timeout(1500)
    step("kb edit", kb_edit)
    def practice():
        pg.goto(B + "#practice"); pg.wait_for_selector("#q-text")
        pg.fill("#q-text", "解释 CAP 定理"); pg.fill("#q-concept", "CAP"); pg.click("text=开始讲解")
        pg.wait_for_selector("#ans"); pg.fill("#ans", "CAP 就是分区时只能选一致性或可用性。"); pg.click("text=提交讲解")
        pg.wait_for_selector("text=v1 的评估", timeout=60000)
        pg.click("text=记为薄弱点 >> nth=0"); pg.wait_for_timeout(500)
        pg.click("text=基于上一版修改"); pg.fill("#ans", pg.input_value("#ans") + " 例如 ZooKeeper 偏 CP。"); pg.click("text=提交讲解")
        pg.wait_for_selector("text=v2 的评估", timeout=60000)
    step("practice create + 2 versions + mark gap", practice)
    def compare():
        boxes = pg.locator("#timeline input[type=checkbox]"); boxes.nth(0).check(); boxes.nth(1).check()
        pg.click("text=对比所选两版"); pg.wait_for_selector("text=版本对比")
    step("compare", compare)
    def hints():
        pg.click("text=💡 提示"); pg.wait_for_selector("#hints .evidence"); pg.click("#hints >> text=太模糊"); pg.wait_for_selector("text=太模糊", timeout=30000)
    step("hint + feedback", hints)
    def scenario():
        pg.click("text=试试情境题"); pg.wait_for_selector("text=评分要点", state="detached", timeout=30000); pg.wait_for_selector("text=情境题"); pg.wait_for_timeout(500)
    step("scenario", scenario)
    def interview():
        pg.goto(B + "#interview"); pg.wait_for_selector("text=开始新面试")
        pg.click("#iv-kind >> text=案例分析"); pg.fill("#iv-role", "咨询"); pg.click('button:text-is("开始")')
        pg.wait_for_selector("#iv-ans", timeout=60000); pg.fill("#iv-ans", "先拆解收入和成本。"); pg.keyboard.press("Meta+Enter")
        pg.wait_for_selector(".msg.me", timeout=60000); pg.click("text=结束并复盘"); pg.wait_for_selector("text=面试总结", timeout=60000)
    step("interview start/answer/end", interview)
    def speech():
        pg.goto(B + "#speech"); pg.fill("#sp-text", "我讲了 RDB，没讲 AOF"); pg.click('button:text-is("分析")')
        pg.wait_for_selector("#sp-title", timeout=60000); pg.fill("#sp-title", "测试复盘"); pg.click("text=保存到学习记录"); pg.wait_for_selector("text=测试复盘")
    step("speech reflect + save", speech)
    def records():
        pg.goto(B + "#records"); pg.wait_for_selector("#gaps")
        pg.click("#gaps >> text=确认 >> nth=0"); pg.wait_for_timeout(500)
        pg.click("#gap-tab >> text=已确认"); pg.wait_for_selector("#gaps >> text=生成闪卡")
        pg.click("#gaps >> text=生成闪卡 >> nth=0"); pg.wait_for_selector("#gd-q", timeout=60000); pg.click("text=保存为闪卡"); pg.wait_for_timeout(800)
        pg.fill("#pref-text", "提示要短"); pg.click("text=保存 >> nth=0"); pg.wait_for_timeout(800)
        pg.click("text=新建领域"); pg.fill("#dn-new", "物理"); pg.click("details[open] button.primary"); pg.wait_for_timeout(800)
    step("gaps confirm -> card draft; prefs; domain", records)
    def cards():
        pg.goto(B + "#cards"); pg.wait_for_selector("text=显示答案"); pg.click("text=显示答案"); pg.click("text=良好"); pg.wait_for_timeout(800)
        pg.click("#fc-tab >> text=AI 生成"); pg.fill("#g-topic", "Redis 持久化"); pg.fill("#g-n", "1"); pg.click("text=生成"); pg.wait_for_timeout(2500)
    step("cards review + generate", cards)
    br.close()
print("\nERRORS:" if errs else "\nno errors", *errs, sep="\n")
