from app import calc


def results(text):
    return [(c["value"], c["ok"]) for c in calc.check(text)]


def test_checks_learner_arithmetic():
    assert results("按公式 30×0.8÷(1−0.8) 约 120 元") == [("120", True)]
    assert results("税后 6%×(1−25%)=4.5%，股权 0.6×12%=6.2%") == [("4.5%", True), ("7.2%", False)]
    assert results("1−(1−0.99)×(1−0.99)=0.999") == [("0.9999", False)]  # precision of the written result
    assert results("20%/30%=0.67") == [("0.666667", True)]               # rounding is fine


def test_units_on_result_only():
    assert results("100×(1+8%)^3=125.97万") == [("125.971万", True)]
    assert results("收入 120×7000=84万") == [("84万", True)]
    assert results("120×7000=94万") == [("84万", False)]


def test_ignores_non_arithmetic_and_unsafe_input():
    assert calc.check("第 3 版比第 2 版好，TCP 三次握手") == []
    assert calc.check("3/0=1") == []
    assert calc.check("9^999=1") == []


def test_chains_and_boundaries():
    # a chain is checked against its last written result
    assert results("0.6×12% + 0.4×6%×(1−25%) = 7.2% + 1.8% = 9%") == [("9%", True), ("9%", True)]
    # an expression touching Chinese text is not cut short ("为1+0.1×10" is not "0.1×10")
    assert results("正确结果为1+0.1×10=2 ms") == [("2", True)]
    assert results("NPV = 994.7−1000=−5.3 万") == [("-5.3万", True)]
    assert results("2^20 约为 104.9 万") == [("104.858万", True)]
    assert results("弧弹性 3000/8500÷20/110=1.94") == [("1.94118", True)]  # "/" as a fraction bar next to "÷"
