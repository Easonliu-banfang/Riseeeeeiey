# Rise Client 中文版

[English](README.md) | **简体中文**

这是 [Rise Client](README.md) 的中文版分支。Rise Client 是一个换皮、性能调优过的
Eaglercraft **26.2** 客户端（浏览器里跑的 Minecraft，Wasm-GC）。

底包是 o_xer 的 Eaglercraft 26.2 移植；Rise 在它之上加了海洋主题、ShadowNet / Sodium
风格的视频设置面板、一堆实用模组和 52 个物品皮肤。

## 这个分支改了什么

原版 Rise 只能显示英文，而且中文界面会因为字体缺字变成方块。本分支把它做成真正的
中文客户端，中英双语可切换。

### 1. 中文不再显示成方块

`build.py` 里的 `trim_unifont()` 为了压体积，把 unifont 里的 CJK 字形全部删掉了
（7.7 MB → 71 KB）。所以游戏本身虽然**自带完整简体中文翻译**（`zh_cn.json`，
8260 条，游戏里的语言菜单就能选），选完却全是方块。

本分支把 CJK 区块补了回去：

| 区块 | 内容 |
| --- | --- |
| U+2E80–2EFF | 部首补充 |
| U+3000–303F | 中日韩符号和标点（、。「」等） |
| U+3040–30FF | 平假名 / 片假名 |
| U+3100–312F、U+31C0–31EF | 注音符号、笔画 |
| U+3200–33FF | 带圈 CJK、CJK 兼容字符 |
| U+3400–4DBF | 扩展 A 区 |
| U+4E00–9FFF | 基本汉字（20992 字） |
| U+F900–FAFF、U+FE10–FE4F | 兼容汉字、竖排形式 |

压缩后字体包只从 71 KB 涨到 0.76 MB，assets 负载 4.81 MB → 5.50 MB。

### 2. Rise 自己的界面汉化

`src/i18n.js` 是一份英文 → 中文的词典（449 条），覆盖视频设置、模组面板、皮肤页、
提示、toast、崩溃恢复按钮等全部界面文字。`src/rise.js` 里的标签、说明、枚举值、
按钮在加载时查表替换；词典里没有的字符串会原样保留英文，不会漏字。

Rise 的界面字体原本是 `rise-font.ttf`（从游戏 `ascii.png` 生成的像素字体，只有拉丁
字形）。中文会回退到系统字体：`PingFang SC / Hiragino Sans GB / Microsoft YaHei /
Noto Sans SC`。

### 3. 界面识别适配中文

Rise 的按钮是「像素级覆盖」在游戏画面上的：它读每一帧的最终画面，用游戏自己的字体
去匹配菜单文字（`Options` / `Video Settings` / `Game Menu` …），从而知道当前是哪个
界面。游戏一切成中文，这些英文就匹配不到了，Mods / 视频设置按钮会消失。

本分支为此做了三件事：

* **补一套中文字形位图。** `tools/gen_glyphs_zh.py` 从 unifont 里取出识别需要的
  24 个汉字（选项 / 视频设置 / 游戏菜单 / 保存并退回到标题屏幕 / 断开连接 …），
  生成 `theme_extra/glyphs_zh.json`。
* **按游戏的渲染尺寸缩放。** Minecraft 画 unihex 字形时 `getOversample() == 2`，
  也就是 16×16 的字形在屏幕上只占 8×8 像素，步进 `width/2 + 1 = 9`。字图集用的是
  `GL_NEAREST` 采样并且 UV 内缩 0.01 texel，所以 8 个屏幕像素并不是简单地把
  2×2 取平均，而是各挑一个 texel：像素 *i* 取 texel
  `floor(0.01 + (i + 0.5) * 15.98 / 8)`。子像素取整会让个别 texel 挪位，因此
  `rise.js` 里存了 4 组候选采样集，逐组尝试、取匹配分最高的那组。
* **按游戏语言切换模板。** Rise 会读游戏 options 里的 `lang`，中文用中文模板，
  英文用英文模板（英文那条路径完全没改）。标题页左下角的版本号
  `Rewritten by o_xer` 是硬编码英文，两种语言下都能用。

另外加了一个不依赖任何文字的热键兜底：**右 Shift** 打开 Rise 面板，
**Alt + 右 Shift** 直接打开模组面板。

### 4. 中英双语切换

视频设置 → 高级 → **语言**，三选一：

| 选项 | 行为 |
| --- | --- |
| 跟随游戏 | Rise 界面跟着游戏语言走，不动游戏设置 |
| 简体中文 | Rise 界面中文，并把游戏语言设成 `zh_cn` |
| English | Rise 界面英文，并把游戏语言设成 `en_us` |

切换后需要重启（面板会提示「应用并重启」）。切换游戏语言不是立刻写 options 文件，
而是记在 `rise.setlang` 里，等下次启动、游戏还没读 options 之前再写进去——否则游戏
退出时会用自己的设置覆盖掉。

**首次启动**（options 里还没有 `lang` 时）会自动把游戏语言设成 `zh_cn`，也就是装完
就是中文的。

## 构建产物

| 文件 | 用途 |
| --- | --- |
| `dist/RiseClient.html` | 离线单文件（76.5 MB），下载后直接打开 |
| `dist/web/` | 托管用的网页版：`index.html` + `payload/*.bin`，首次加载后缓存在浏览器里 |
| `docs/` | 与 `dist/web/` 相同，方便开 GitHub Pages |

## 重新构建

```
# 1. 生成中文字形数据（会下载 GNU Unifont 17.0.01 到 .unifont-cache/）
.venv/bin/python tools/gen_glyphs_zh.py

# 2. 完整重建（需要 ref/wispcraft-26.2.html 底包，不在本仓库里）
.venv/bin/python gen_textures.py
.venv/bin/python gen_extras.py
.venv/bin/python gen_skins.py
python3 build.py

# 或者：在已构建好的 dist/ 与 docs/ 上就地重打（不需要底包）
.venv/bin/python tools/i18n_build.py            # --check 只看会改什么
```

`tools/i18n_build.py` 做的是和 `build.py` 完全相同的编辑，只不过作用在仓库里已经
构建好的产物上：换掉内联的 `i18n.js + rise.js`（Blueprint 源码不在本仓库，所以从
现有构建里原样取回来）、把 CJK 字形补进 assets 包的 `unifont.zip`、刷新 web 版的
负载和缓存版本号、把 `dist/web/` 同步到 `docs/`。

## 测试

`tools/test_i18n.js` 在 jsdom 里把构建好的 `rise.js` 真正跑一遍：检查界面文字、
用 Minecraft 自己的 unihex 几何合成一帧带中文标题的画面、验证界面识别、再跑一遍
英文回归。

```
npm i jsdom
NODE_PATH=<node_modules> node tools/test_i18n.js
```

## 许可与致谢

* Eaglercraft 26.2 由 o_xer 制作，基于 lax1dude 的 EaglercraftX 1.8。
* 汉字字形来自 [GNU Unifont](https://unifoundry.com/unifont/) 17.0.01
  （GPL-2.0-or-later，含字体嵌入例外），原样打包在 `assets/minecraft/font/unifont.zip`。
* Minecraft 版权归 Mojang 所有。
