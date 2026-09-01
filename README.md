# 能碳监测平台

**面向智算中心的低碳算力能碳管理平台。**

跑在你自己电脑上的分析工具：接入机房的用电台账、硬件功耗和任务日志，由一个 AI Agent 自动找出高能耗阶段、测算算力碳足迹、分析能源成本和碳资产，形成可复用的低碳算力管理工作流。

支持 Windows 和 macOS。

📖 **完整产品文档见 [CLAUDE.md](./CLAUDE.md)** —— 功能设计、计算公式、技术方案、开发路线图。

---

## 当前状态

🚧 **产品文档已定稿（v2.0），代码尚未开始编写。**

下面的安装启动说明是为阶段一完成后准备的，现在还跑不起来。

进度详见 [CLAUDE.md 第 17 节 · 开发路线图](./CLAUDE.md#17-开发路线图)。

---

## 它能做什么

| 模块 | 回答什么问题 |
|---|---|
| 📥 **数据接入** | 把台账文件、GPU 实时功耗、任务日志汇到一处 |
| 🔥 **高能耗识别** | 哪段时间在费能？费在 IT、制冷还是供配电？ |
| 🌱 **碳足迹测算** | 这个月/这个任务/这批设备排了多少碳？（地域法 + 市场法双算法） |
| 💰 **成本与碳资产** | 电费怎么构成的？哪些时段又贵又脏？履约缺口有多大？ |
| 🔄 **工作流** | 把上面几步固化成每月照着跑的固定动作，措施效果下期自动回测 |
| 🤖 **Agent** | 自动归因、给减碳建议、写报告初稿 |

支持的文件格式：**Excel (.xlsx/.xls)**、**CSV**、**PDF**、**Word (.docx)**

---

## 关于数据安全（重要，先读这段）

这个平台会用到云端 AI 模型，所以必须把边界说清楚：

**留在你本机的**
- 所有原始明细数据（逐条功耗记录、设备序列号、机房位置、文件原文）
- 整个数据库 `data/app.db`

**会发给 AI 模型的**
- 只有聚合统计量，比如「7月3日 14:00-18:00 平均功率 420kW，较基线高 38%」
- 每次发送前，界面会**完整展示将要发出的内容**，你确认才发

**如果你不想用 AI**
- 设置里有**纯本地模式**开关。关掉之后，测算、图表、成本分析、导出**全部照常可用**，只是没有智能归因和建议
- 不填 API 密钥也能正常使用平台，只是 Agent 功能不可用

详见 [CLAUDE.md 第 10.4 节 · 数据边界的具体执行](./CLAUDE.md#104-数据边界的具体执行)。

---

## 怎么装（阶段一完成后适用）

### 第一步：安装 Python

先检查电脑上有没有 Python。

**Windows**：按 `Win + R`，输入 `cmd` 回车，在黑窗口里输入：
```
python --version
```

**macOS**：打开「终端」（在启动台里搜索「终端」），输入：
```
python3 --version
```

显示 `Python 3.11.x` 或更高就跳到第二步。提示找不到命令，就去 [python.org/downloads](https://www.python.org/downloads/) 下载安装。

> ⚠️ **Windows 用户注意**：安装界面最下方有个 **「Add Python to PATH」** 勾选框，**一定要勾上**，否则后面所有命令都会失败。

### 第二步：下载本项目

把项目文件夹放到你找得到的位置，比如 `D:\能碳监测平台` 或 `~/文稿/能碳监测平台`。

### 第三步：安装依赖

**Windows**（在项目文件夹里按住 `Shift` + 右键 → 「在此处打开 PowerShell 窗口」）：
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**macOS**（在「终端」里，先 `cd` 到项目文件夹）：
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

这一步会下载几个工具包，要几分钟，最后显示 `Successfully installed ...` 就成功了。

> 💡 `.venv` 是个「独立环境」，把这个项目用的工具包单独装在项目文件夹里，不会影响你电脑上的其他程序。

### 第四步：配置 API 密钥（只有要用 Agent 才需要）

**Windows**
```powershell
copy .env.example .env
```

**macOS**
```bash
cp .env.example .env
```

然后用记事本/文本编辑器打开 `.env`，把密钥填进去。

> 🔒 `.env` 已经在 `.gitignore` 里，不会被提交到仓库。**不要把密钥贴进任何代码文件或聊天记录。**
>
> 跳过这一步也能正常用平台，只是 Agent 功能不可用。

---

## 怎么启动

**每次使用都执行这两条命令：**

**Windows**
```powershell
.venv\Scripts\activate
streamlit run app.py
```

**macOS**
```bash
source .venv/bin/activate
streamlit run app.py
```

浏览器会自动打开 `http://localhost:8501`，看到界面就成功了。

**关闭平台**：回到命令窗口按 `Ctrl + C`（Mac 是 `Control + C`）。

> 到了[阶段五](./CLAUDE.md#-阶段五--打包分发)会打包成双击即用的启动包，那时就不用敲命令了。

---

## 出问题了怎么办

| 提示信息 | 什么意思 | 怎么解决 |
|---|---|---|
| `python 不是内部或外部命令` | 电脑找不到 Python | 重装 Python，记得勾「Add Python to PATH」 |
| `ModuleNotFoundError: No module named 'xxx'` | 少装了一个工具包 | 重跑 `pip install -r requirements.txt` |
| `Port 8501 is already in use` | 端口被占用 | 换端口：`streamlit run app.py --server.port 8502` |
| 浏览器没自动打开 | 正常现象 | 手动输入 `http://localhost:8501` |
| 提示「未配置 API 密钥」 | 没填 `.env` | 只影响 Agent，其余功能正常。要用就填密钥 |
| `pip` 下载很慢或超时 | 网络问题 | 换镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 解析出来的数据不对 | PDF/Word 解析本就不保证 100% 准确 | 在「待确认预览区」手工改正再入库，这是设计好的环节 |
| 提示读不到 GPU 功耗 | 机器上没有 NVIDIA 卡或没权限 | 不影响其他功能，改用文件导入台账 |

---

## 数据存在哪

| 位置 | 是什么 |
|---|---|
| `data/app.db` | 你的所有数据。**想备份就复制这一个文件。** |
| `data/factors.csv` | 排放因子表，可直接用 Excel 编辑 |
| `data/tariff.csv` | 分时电价表 |
| `data/embodied.csv` | 设备隐含碳表 |
| `data/versions/` | 上面三张表的历史版本快照 |
| `data/agent_audit.log` | Agent 每次调用的审计日志，可查发出过什么 |
| `.env` | 你的 API 密钥（不进 Git） |

---

## 重要提醒

⚠️ 内置的**排放因子**是参考值，正式使用前请按你所在地区、年份的官方发布数据核对更新。

⚠️ **电价表和 PUE 必须按你的实际情况填写**，内置值仅为示例，直接用会算错。

⚠️ **Agent 给的是分析建议，不是结论**。碳排放数字以平台的确定性计算为准，Agent 的话请自行核实。

⚠️ 本平台输出的是**内部分析结果**，不能直接用于 ISO 14064 / ISO 14067 等第三方核证提交。
