# llm-design-share — 面壁 AI 面试训练系统

第 68 组的脱敏共享副本，供队友阅读代码、讨论方案和本地试用。

## Proposal

- [阅读 proposal（PDF）](proposal/group68_proposal.pdf)
- [LaTeX 源文件](proposal/group68_proposal.tex)

采用 NeurIPS 2026 模板，省略摘要。**当前为团队讨论草稿；正式提交前必须补齐所有成员的姓名、学号和香港大学邮箱。** 请勿把含成员学号、邮箱的提交版直接放入公开仓库。

## 已包含的功能

- Markdown 知识库与 Memsearch 检索。
- 技术、行为、系统设计三类模拟面试及知识库辅助反馈。
- SenseVoice 本地语音转写，以及通过配置的 LLM 服务生成复盘。
- 闪卡增删、导入导出、生成和到期复习。

现有闪卡使用固定 1/3/7 天规则；proposal 中的完整 SM-2、统一检索与实验评估属于计划工作。本仓库不声称已有可复现的命中率或学习效果结果。

## 本地启动

需要 Python 3.10+ 和 macOS / Linux；首次安装依赖及模型需要联网。

```bash
# 从共享仓库下载 llm-design-share.zip 并解压
cd llm-design-share
cp .env.example .env
# 在本机 .env 中填入自己的 LLM_API_KEY、LLM_BASE_URL 和 LLM_MODEL
bash start.sh
```

打开 http://127.0.0.1:8000 。不需要 LLM 的功能可单独使用；模拟面试和 AI 生成功能需要有效的服务配置。

知识库、会话和闪卡从空数据开始。在页面粘贴非敏感的技术资料或手动添加测试卡片即可试用。运行数据由程序生成，已加入忽略规则。

## 共享范围与数据处理

- 本副本不包含原有面试会话、复盘、个人学习进度、第三方面经全文或旧论文生成脚本。
- 未复制原仓库 Git 历史；仓库从干净的首次提交开始。
- 保留必要源码、项目内技能文件和配置示例；不包含真实 API 凭据。
- 服务默认仅监听 127.0.0.1。当前没有多用户登录与权限隔离，不应直接作为公网服务部署。
- 本地语音识别不等于全流程离线：调用评分、总结或闪卡生成时，相应文本和检索片段会发送到你配置的模型服务。
- 上传新文件前检查内容；.gitignore 不会自动清除已经被 Git 跟踪的敏感内容。

## 项目结构

```text
app/          后端、前端、闪卡脚本与依赖的技能文件
proposal/     共享版提案 PDF 与 LaTeX
知识库/       本机知识库（运行数据不提交）
data/         本机闪卡（运行数据不提交）
.env.example  空凭据配置示例
```

## 组件来源

本项目基于现有 Agent-design 原型整理。保留了 Memento 闪卡和系统设计提示文件中的上游署名；使用 [Memsearch](https://github.com/zilliztech/memsearch)、[Hermes Agent](https://github.com/NousResearch/hermes-agent) 相关组件，以及 [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)。本仓库不包含完整 Hermes 运行时；组件许可依各自上游规定。

## 验证范围

共享前进行静态敏感信息扫描、Python 语法检查、忽略规则检查和空闪卡存储检查。未在此过程调用付费 LLM、下载语音模型或完成端到端运行验证。
