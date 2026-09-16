# 化工询盘台（Chemical Trade AI Copilot）

面向化工外贸业务员的**一次性工具**：把客户询盘变成可核查的技术回复。

> 输入询盘 → 证据约束的结论 → 导出 → 关闭。**不保存任何数据。**

## 它做什么

- 只用企业批准的 TDS/SDS；每条结论都带产品、文件名与**物理页码**，可在界面点开真实 PDF 原页核对。
- 高风险参数（HDT / Tg 等）必须与固化剂、配比、固化制度、测试方法**整组绑定**，缺一即整条丢弃。
- 证据不足、或模型输出未通过本地确定性门禁时，**明确拒答**，不显示任何未核验数值。
- 输出可编辑的英文回复草稿；**不自动发送**，不连接邮箱。
- 一键导出 **Markdown** 与 **可打印 HTML**（浏览器打印即得 PDF），文件在内存中生成。

## 不做什么

不自动发送邮件；不提供价格、库存、MOQ、交期；不做 CRM / ERP；不做通用 PDF 问答；无账号、
无历史记录、无持久化；不抓取资料、不绕过登录或付费墙。

## 运行前提

- Python **3.11–3.13**
- 已批准的 TDS/SDS 资料根目录（默认 `G:\桌面\化工`）
- 一份与该资料清单**指纹匹配**的 Chroma 索引（默认仓库内 `.chroma`）
- `DEEPSEEK_API_KEY`

## 首次安装

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

建立索引（资料根按本机实际路径填写）：

```bat
.venv\Scripts\python.exe -m chemical_trade_copilot.cli rebuild ^
  --materials-root "G:\桌面\化工" ^
  --catalog materials_catalog.json ^
  --database .chroma ^
  --golden-cases tests\fixtures\golden_retrieval_cases.json
```

机器相关配置写进 `.env.local`（该文件不入 Git）：

```
DEEPSEEK_API_KEY=...
CHEMICAL_TRADE_MATERIALS_ROOT=G:\桌面\化工
```

`CHEMICAL_TRADE_DATABASE` 与 `CHEMICAL_TRADE_MATERIAL_CATALOG` 默认指向仓库内，通常无需设置。

## 启动

双击 **`启动化工询盘台.bat`**，或：

```bat
.venv\Scripts\python.exe -m streamlit run src\chemical_trade_copilot\streamlit_app.py
```

界面语言：右上角切换，或在地址后加 `?lang=zh-CN` / `?lang=en`。

## 测试

```bat
.venv\Scripts\python.exe -m pytest -q
```

## 边界

本工具的结论严格受**已批准资料范围**限制（产品、文件版本、适用地区）。资料年代与地区差异是
实质性限制；合规、商务、物流与专业化工判断必须由人确认，系统不代签。

## 目录

| 路径 | 作用 |
|---|---|
| `src/chemical_trade_copilot/streamlit_app.py` | 单页界面入口 |
| `src/chemical_trade_copilot/inquiry_analysis.py` | 检索规划、证据门禁、结构化分析（**核心，改动需谨慎**） |
| `src/chemical_trade_copilot/export_bundle.py` | 导出组装（纯函数，不落盘） |
| `src/chemical_trade_copilot/localization.py` | 中英界面文案 |
| `materials_catalog.json` | 批准资料清单（唯一事实源） |
| `tests/fixtures/golden_retrieval_cases.json` | 检索验收用例（正向 + 负例） |
| `PRESERVATION.md` | 本仓库的来源与保留说明 |
| `CURRENT_WORK.md` | 仅在长任务进行期间存在的状态载体 |
