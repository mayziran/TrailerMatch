# TrailerMatch

预告片自动匹配工具：扫描预告片与正片目录，通过 AI 分析文件名将预告片匹配到对应电影，并按 [Emby 预告片命名规范](https://emby.media/support/articles/Trailers.html) 移动到电影文件夹并重命名。

## 功能特性

- 左侧选择预告片目录（支持正则筛选，如 `sample\.mp4$`），右侧选择正片目录（每部电影一个子文件夹）
- 基于 OpenAI 兼容接口（OpenAI / DeepSeek / 通义 / Azure / 本地 Ollama 等）进行名称匹配
- 两种匹配模式：
  - **批量模式**：所有预告片与正片名一次调用，一次返回全部匹配（默认推荐）
  - **逐条候选模式**：每个预告片先本地模糊筛选 top-N 候选再单独调用 AI 确认（适合正片库极大的场景）
- 匹配结果表格可视化，支持手动改选正片、置信度门槛、多预告片冲突标记
- 确认后按 Emby 规范移动到正片文件夹并重命名为 `电影名-trailer.扩展名`

## 安装

### Windows 用户（推荐）

直接到 [Releases](https://github.com/mayziran/TrailerMatch/releases) 下载最新的 `TrailerMatch.exe`，双击即可运行，无需安装 Python。版本号显示在窗口标题栏（如 `TrailerMatch v1.0.0`）。

### 源码运行

需要 Python 3.10+：

```bash
pip install -r requirements.txt
python main.py
```

## 使用说明

1. 点击「AI 设置」配置 API Base URL / Key / 模型（OpenAI 兼容格式）
2. 左侧选择预告片文件夹，可添加正则筛选规则；**选定目录后自动扫描**，也可点击「扫描预告片」手动重扫
3. 右侧选择正片目录（每个电影一个子文件夹），同样**选定后自动扫描**，或点击「扫描正片」
4. 点击「开始匹配」，查看 AI 匹配结果（匹配 / 未匹配 / 冲突）
5. 勾选确认项，点击「确认并移动」完成移动与重命名

## Emby 预告片命名

移动后的文件按 Emby 规范命名，预告片与正片放在同一文件夹。预告片以**正片主视频文件名**（去扩展名）为基准重命名，而非文件夹名：

```
/Movies
  /Home Alone (1990)
    Home Alone (1990).mkv
    Home Alone (1990)-trailer.mp4
```

参考：[Emby Trailer Naming](https://emby.media/support/articles/Trailers.html)

## 配置说明

- 配置文件保存在用户主目录 `~/.trailermatch/config.json`（含 API Key），不会进入代码仓库
- **最低置信度**：AI 匹配分数低于该值视为未匹配
- **候选正片数量**：逐条候选模式中每个预告片发给 AI 的正片候选数
- 正则筛选采用「命中即视为预告片」语义；留空则收录全部视频文件

## 许可证

[MIT](LICENSE)
