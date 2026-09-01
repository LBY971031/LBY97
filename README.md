# 能碳监测平台

一个运行在你自己电脑上的本地文件分析工具，用来分析**产品用能报告**和**碳足迹数据**。

支持 Windows 和 macOS，数据全部保存在本机，不联网、不上传。

📖 **完整产品文档见 [CLAUDE.md](./CLAUDE.md)** —— 包含功能设计、技术方案、开发路线图。

---

## 当前状态

🚧 **产品文档已定稿，代码尚未开始编写。**

下面的安装启动说明是为阶段一完成后准备的，现在还跑不起来。

进度详见 [CLAUDE.md 第 11 节 · 开发路线图](./CLAUDE.md#11-开发路线图)。

---

## 三大功能模块

| 模块 | 干什么 |
|---|---|
| ⚡ **用能分析** | 导入电、水、气、蒸汽、燃油台账 → 自动换算单位、看趋势、找能耗大户 |
| 📦 **物质使用分析** | 导入物料清单 / BOM → 看用量排名、算损耗率、揪出异常 |
| 🌱 **碳排放分析** | 导入碳数据（或用内置因子表换算）→ 看总量和构成 |

支持的文件格式：**Excel (.xlsx/.xls)**、**CSV**、**PDF**、**Word (.docx)**

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

如果显示 `Python 3.11.x` 或更高版本，跳到第二步。

如果提示找不到命令，去 [python.org/downloads](https://www.python.org/downloads/) 下载安装。

> ⚠️ **Windows 用户注意**：安装界面最下方有个 **「Add Python to PATH」** 的勾选框，**一定要勾上**，否则后面所有命令都会失败。

### 第二步：下载本项目

把项目文件夹放到一个你找得到的位置，比如 `D:\能碳监测平台` 或 `~/文稿/能碳监测平台`。

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

这一步会下载几个工具包，需要几分钟，看到最后显示 `Successfully installed ...` 就是成功了。

> 💡 `.venv` 是一个「独立环境」，作用是把这个项目用的工具包单独装在项目文件夹里，不会污染你电脑上的其他程序。

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

**关闭平台**：回到命令窗口，按 `Ctrl + C`（Mac 是 `Control + C`）。

> 到了[阶段三](./CLAUDE.md#-阶段三--打包分发)，会打包成双击即可运行的启动包，那时就不用敲命令了。

---

## 出问题了怎么办

| 提示信息 | 什么意思 | 怎么解决 |
|---|---|---|
| `python 不是内部或外部命令` | 电脑找不到 Python | 重装 Python，记得勾选「Add Python to PATH」 |
| `ModuleNotFoundError: No module named 'xxx'` | 少装了一个工具包 | 重新执行 `pip install -r requirements.txt` |
| `Port 8501 is already in use` | 端口被占用了 | 换个端口：`streamlit run app.py --server.port 8502` |
| 浏览器没自动打开 | 正常现象 | 手动在浏览器输入 `http://localhost:8501` |
| `pip` 下载很慢或超时 | 网络问题 | 换国内镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 解析出来的数据不对 | PDF/Word 解析本来就不保证 100% 准确 | 在「待确认预览区」手工改正后再入库，这是设计好的环节 |

---

## 数据存在哪

| 位置 | 是什么 |
|---|---|
| `data/app.db` | 你的所有数据。**想备份就复制这一个文件。** |
| `data/factors.csv` | 排放因子表，可以直接用 Excel 打开编辑 |
| `data/factor_versions/` | 因子表的历史版本快照 |

数据全部在本机，不会上传到任何地方。

---

## 重要提醒

⚠️ 内置的排放因子是**参考值**，用于让平台开箱即用。正式使用前请按你所在**地区、年份、行业**的官方发布数据核对更新。

⚠️ 本平台输出的是**内部分析结果**，不能直接用于 ISO 14064 / ISO 14067 / CBAM 等第三方核证提交。
