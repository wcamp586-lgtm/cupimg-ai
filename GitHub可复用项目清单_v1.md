# GitHub 可复用项目清单 v1

1688 杯具 AI 作图 · 现成项目拼装评估 · 核查日期 2026-11-06
数据来自 GitHub API 实测（star / license / 最近推送）与仓库源码实读。star 数为核查当日快照。
分类口径：**A 直接采用**（装了就用）/ **B 部分复用**（改规则或接口）/ **C 仅参考**（读思路、不复制代码）/ **D 明确不用**。

## A. 直接采用

| 项目 | star | 许可 | 复用什么 | 拼到哪一步 |
| --- | --- | --- | --- | --- |
| `danielgatis/rembg` | 25,351 | MIT（代码） | 抠图 CLI / Python API / HTTP server；模型切换参数 | M0/M1 抠图 |
| `timgit/pg-boss` | 4,125 | MIT | PostgreSQL 持久化任务队列，正好配报告 v2 的 PG17 | M1 任务编排 |
| `vercel/satori` | 14,167 | MPL-2.0 | JSX/CSS → SVG，flex 自动布局、中文换行、字体度量 | M1 服务端排版 |
| `lovell/sharp` | 未逐一复核 | Apache-2.0 | SVG/PNG 栅格化、合成、尺寸格式转换、EXIF 剥离 | M1 合成导出 |
| `konvajs/konva` | 未逐一复核 | MIT | 浏览器端改字、拖拽、选稿 | M2 网页改稿 |
| `contentauth/c2pa-js` | 40 | MIT | 浏览器/Node 侧读写 C2PA 清单 | §04 AI 隐式标识 |
| `contentauth/c2patool` | 164 | Apache-2.0 | 命令行注入/校验文件元数据清单（JPEG/PNG/PDF） | §04 AI 隐式标识 |
| `tencentyun/cos-js-sdk-v5` + `qcloud-cos-sts` | 官方 | 官方 SDK | 浏览器直传 COS、服务端 STS 临时签名（官方有 Node 示例） | 步骤 2 上传 |

要点：
- **rembg 的许可陷阱**：代码 MIT，但模型权重各有一套许可。2.0.80 起默认 `bria-rmbg`（BRIA RMBG-2.0）是 **CC BY-NC 4.0，商业使用需另签协议**，且 1GB 模型在 2C4G 上易 OOM。必须显式指定 `-m isnet-general-use -vm`（ISNet + ViTMatte，Apache-2.0）或 `u2netp` / `u2net`。第三方 2026-10 实测：ISNet+ViTMatte 在 AIM-500 上错误率最低、CPU 约 1.7 秒/张；u2net 最快约 0.12 秒/张。**结论：把报告 v2 的 u2netp 起步改为 ISNet+ViTMatte 优先、u2net 保底，Stage A 用真杯图对比后再定**（第三方实测，需自验）。
- Satori 是 MPL-2.0（文件级弱 copyleft）：作为依赖库调用没问题，但**别修改它的源码文件后闭源分发**。中文必须用完整版思源黑体（精简版/Variable 字体会出方块乱码），所有 flex 容器要显式写 `display: flex`。
- c2pa 是国际标准，用于承载"隐式标识"的技术实现；我国《标识办法》要求的字段（生成属性、服务提供者名称/编码、内容编号）需**额外补齐**，不能只写 C2PA 就当合规。

## B. 部分复用（改一改就能用）

| 项目 | star | 许可 | 具体文件 / 模块 | 要改什么 |
| --- | --- | --- | --- | --- |
| `xianyu110/ecommerce-image-skills` | 151 | **MIT** | `scripts/check_main_image.py`（白底占比/主体占比/尺寸检查 + 自动修复）、`stitch_long_image.py`（详情长图拼接切片）、`crop_to_modules.py`、`make_grid.py`、`batch_edit.py`（批量换背景，**断点续跑 + 预算上限**）、`generate.py`（OpenAI 兼容生图） | 检查规则从 Amazon（#FFFFFF、≥85%、1000px）改成 1688 类目（800×800 等，按商家后台现行规则）；`generate.py` 换成本项目的模型适配层；**不要用它 README 里推荐的第三方中转/镜像 API** |
| `aks-666888/compliance-check` | 0 | MIT | `dict/words.json`：76 条词库（广告法极限词 40+ 条 + 医疗/财经/教育/美妆高危词）、12 组变体规则（谐音/拼音/emoji） | 抄词表进 `forbidden_words`，补 1688 类目词，加上下文豁免（"第一次使用"不报"第一"） |
| `mengbao/content-compliance-checker` | 未逐一复核 | 未逐一复核 | 上下文感知判定、风险分级、结构化报告 | 只借鉴判定逻辑，代码按需自写 |
| `ZhengPeng7/BiRefNet` | 4,371 | MIT | 抠图精度最好的开源权重，商用友好 | **首版不上**：CPU 上第三方实测 16–91 秒/张，2C4G 扛不住。等有 GPU 或作为透明杯兜底方案再评 |
| `geongeorge/picture-it` | 未逐一复核 | 未逐一复核 | `satori-jsx.ts` / `compositor.ts` / `pipeline.ts`：JSX→SVG→PNG→Sharp 合成的完整三段式管线，含可序列化 JSON 设计树 | 参考它的 `SatoriJSX` 数据类型设计，正好对应我们的 `design.json` |

补充参考：
- `yisibl/resvg-js`（SVG→PNG，Rust）可作 Satori 输出的备选栅格化器；Sharp 更快（第三方实测约 200ms/张 vs resvg 400ms）。
- `PaddlePaddle/PaddleOCR`：仅当程序规则不足以查图上文字越界时引入，先用规则。
- `BerriAI/litellm`：供应商多到需要网关时再引入；先用自写薄适配层。

## C. 仅参考（不要复制代码）

| 项目 | star | 许可 | 为什么不能直接用 | 能学什么 |
| --- | --- | --- | --- | --- |
| `liangdabiao/ecom-details-image` | 1,599 | **无 LICENSE 文件** | 法律上默认"保留所有权利"，**代码不可复制进商业项目**；且生图走 apiz 第三方中转 CLI，与本项目"只用正式 API"冲突 | 25 个场景模板结构、Campaign Style Lock（整套图锁定色板/光线/字体）、5 主图 + 7–9 详情的编排、参考图先上传换公网 URL 再图生图以保证外观准确、Prompt 精简原则 |
| `buluslan/gpt-image2-ecommerce` | 未逐一复核 | 未逐一复核 | 提示词模板源项目，需确认许可 | 场景模板分类 |
| `xianyu110/ecommerce-image-skills` 的 skill 文档 | 151 | MIT | 文档可复用，但其"产品身份锁定"是把形状/颜色/Logo/文字原样带进每条提示词——**我们需要更硬的保证：抠图保留主体**，不能只靠提示词 | 产品身份锁定思路、平台规格表（淘宝 750 宽详情等） |

## D. 明确不用（本阶段）

`comfyanonymous/ComfyUI`（自部署生图，2C4G 无 GPU 不现实）、`n8n-io/n8n`（Sustainable Use License，运营连接后期再说）、`langgenius/dify`（多租户与前端标识有附加条件）、`langfuse/langfuse`（先用本地日志）、PhotoShop UXP 桌面执行器（无真实 PSD 需求）。维持报告 v2 的"按需求加入"判断。

## 拼装后的系统骨架（一句话版）

```
COS 直传(官方SDK) → rembg/ISNet 抠图 → 模型适配层(自写: 百炼+方舟/国际版双地域)
→ Satori+Sharp 排版合成 → 四道合规校验(自写: 极限词表 + C2PA标识 + 1688图规 + 字体白名单)
→ 导出包(final/editable/design.json/report) → pg-boss 队列串起来 → Web(Konva) 改稿
```

**手搓清单（拼不上的部分）**：模型适配层、商品事实表单与结构化输出、四道校验中间件、`design.json` 设计数据与版本、多租户 + 成本账本 + 审计、CDR 可编辑导出映射。这六块是项目的真正工作量，其余尽量拼现成。

## 核实记录与配额

- 2026-11-06 通过 GitHub REST API 核实 star / license / 推送日期；`liangdabiao/ecom-details-image` 返回 `license: null`（仓库内确无 LICENSE 文件），`xianyu110/ecommerce-image-skills` 为 MIT 且 LICENSE 全文已实读。
- 两个核心仓库已 `git clone --depth 1` 到 `_github_refs/`，源码结构已实读（`check_main_image.py` 检查逻辑、`SKILL.md` 编排流程）。
- 未认证 API 配额 60 次/小时，本轮约用 30 次；`git clone` 与网页浏览不消耗配额。暂不需要 token。
