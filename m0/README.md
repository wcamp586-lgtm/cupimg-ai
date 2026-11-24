# M0 单图竖切骨架（offline + live 均已实跑通过）

> **2026-11-06 已上线内测**：`https://cupimg.aicloud.plus`（访问口令见 `deploy/.env.production`）。
> Web 端在 `webapp/`，部署配置在 `deploy/`，上线包 `cupimg_bundle.tar.gz`。
> 线上 live 全链路与重启回归均 `PIPELINE_OK / READY`，ZIP 下载 CRC 校验通过。
> 完整交付口径见《1688杯具AI作图_线上内测试用说明_v1》（md + html）。
> 产物仍**禁止直接上架 1688**，需先换美工实拍图过 Stage A 门禁。

**一句话**：给一张杯子实拍图，一条命令走完 10 个环节，产出 1688 主图 + 场景图 + 详情图 + CDR 可编辑 SVG + 合规报告 + 生成存证。

**这不是产品代码。** 它是一次性验证链路的可丢弃脚本（throwaway vertical slice），用来在写代码之前先回答："这条路走不走得通、每一环该产出什么、哪些能抄现成的"。产品实现仍按《技术架构报告 v2》的 Node/TypeScript + Fastify + pg-boss + OSS。

## 三步跑起来（0 元、0 Key、0 联网）

```bash
cd m0
python -m pip install pillow numpy
python run.py                 # 自动生成 demo 杯图并跑完全流程
```

看到 `PIPELINE_OK ✅ | 交付: NEEDS_REVIEW | 成本: 0.0 元` 即成功。产物在 `out/demo/DEMO-001/`。

`NEEDS_REVIEW` 是**故意的**：offline 模式四个模型环节都是本地桩，只能证明管线通，不能证明杯子还原度。别把桩图拿去上架。

## 换成你自己的图

```bash
python run.py --input "美工实拍/玻璃杯01.jpg" --facts my_sku.json
```

`my_sku.json` 必填 5 个字段（缺一即拒绝出图，禁止 AI 臆造）：

```json
{"sku":"CUP-001","name":"双层玻璃杯","material":"高硼硅玻璃",
 "capacity_ml":350,"color":"透明","logo_text":"你的品牌","has_handle":true}
```

## 接真实模型（仍可 0 元）

本机 `.env` 已由 `tools/` 下的登录/建 Key 脚本写入百炼 Key，**无需手填**。

```bash
python tools/smoke_api.py     # 验证 Key 与 VL/文案两个模型
python tools/smoke_image.py   # 验证百炼生图免费额度（生成 1 张空场景，0 元）
python run.py --mode live --input 实拍.jpg --facts my_sku.json
```

**2026-11-06 实测状态**

| 项 | 状态 |
|---|---|
| 百炼登录态 | 已保存到 `.secrets/aliyun_state.json`（本机，已 gitignore） |
| 免费额度 | `qwen3-vl-plus` 1M、`qwen3.7-plus` 1M；**`qwen-image-3.0` / `3.0-pro` 各 10 张**，均到期 2027/01/29 |
| 「免费额度用完即停」 | **这 4 个模型已开启**（最小影响面），账号其余模型保持原状 |
| API Key | 已写入 `.env`；首次创建时明文曾误入调试输出，已「重置」使旧值作废，当前为重置后的新值 |
| 真实联调 | `smoke_api.py` → TEXT/VL 均 `HTTP 200`；`smoke_image.py` → `HTTP 200 / 1024×1024 / 0 元` |
| 生图 | **不用注册 BytePlus**：百炼 `qwen-image-3.0` 已接入 `generate_scene()` 并真实出图 |
| 抠图 | `rembg[cpu]` + onnxruntime 已装；**联调临时用 `u2netp`（4.6 MB，官方 MD5 已校验）**，生产仍以 `isnet-general-use` 为准 |
| **live 全链路** | ✅ **已跑通**：`PIPELINE_OK / READY / 桩环节：无 / 0.0049 元 / 89s`，产物在 `out/demo_live/DEMO-001/` |

**live 实跑命令与结果**（`REMBG_MODEL=u2netp` 只为快速验证链路，不改 `.env` 默认生产选型的 `isnet-general-use`）：

```bash
REMBG_MODEL=u2netp python run.py --mode live --tenant demo_live
# 链路: PIPELINE_OK ✅ | 交付: READY | 成本: 0.0049 元 | 耗时: 89.4s | 桩环节: 无
# 账本: vision OK / copy OK / cutout OK / scene OK，无 UNKNOWN
# 合规: 极限词、文字越界、字体授权、AI 标识、1688 图规、预算、调用状态 —— 7 项全 PASS
```

**这次实跑抓到并修掉一个真 bug**：`qwen3.7-plus` 生成的长标题溢出详情图右边界，而原合规四件套只查极限词不查排版。已在 `compose.py` 加 `fit_text()`（按真实字体度量裁断，PNG 与 SVG 共用同一结果），并在 `compliance.py` 新增 `text_fit` 硬校验项；复跑后标题以省略号收在画布内。**注意：`READY` 只代表程序硬校验通过，demo 杯图是程序画的，杯子还原度仍必须用美工实拍图验收，不许上架。**

- **重要口径修正**：百炼账号自带生图免费额度，同一个 Key、同一个专属域名走 `POST /images/generations`（OpenAI 兼容模式）即可，`size` 用 `1024x1024`（字母 `x`）。BytePlus 从「阻塞项」降为 Stage A 的 Seedream 4.5 / qwen-image 质感 A/B 对比项。
- 双供应商保留在代码里：`SCENE_PROVIDER=auto` 时填了 `BYTEPLUS_API_KEY` 优先 Seedream，否则自动走百炼；也可强制 `byteplus` / `dashscope`。
- 文案模型从 `qwen-plus` 改为 `qwen3.7-plus`：**qwen-plus 本体无免费额度**（控制台列在「额度用尽或过期」，剩余 `-`）。
- `DASHSCOPE_BASE` 用控制台给的**业务空间专属域名**；旧 `dashscope.aliyuncs.com` 自 2026-09-30 起进入维护状态，不再支持新特性。
- `live` 抠图需 `pip install "rembg[cpu]" onnxruntime`，首次自动下载模型权重；未装时 `cutout()` 会抛错使链路失败——这是刻意的，不用桩冒充真实抠图。
- 超时记 `UNKNOWN` 且不重发（可能已计费）。计费保护：百炼「免费额度用完即停」已开；BytePlus 开户后须开「Free Tokens Only」。

## 各环节拼装来源

| 环节 | 来源 | 许可 | 本骨架里的落点 |
|---|---|---|---|
| 1688 图规校验（白底/主体占比/尺寸/自动修图） | `xianyu110/ecommerce-image-skills` → `scripts/check_main_image.py` | **MIT** | `vendor/check_main_image.py`，保留 `analyse()/fix()` 原逻辑，新增 `check_1688()` 改阈值到 800×800；许可证全文在 `vendor/LICENSE.ecommerce-image-skills.txt` |
| 详情模块裁切思路 | 同上 → `crop_to_modules.py` | MIT | 未复制，`ImageOps.fit` 思路留到 M2 |
| 断点续跑 / 预算硬上限 / CSV 日志 | 同上 → `batch_edit.py` | MIT | 未复制（它绑定第三方中转 `generate.py`），机制重写进 `pipeline/adapters.py::CallLedger` |
| 详情长图拼接 | 同上 → `stitch_long_image.py` | MIT | 后置到 M2 |
| 商品主体抠图 | `danielgatis/rembg` + `isnet-general-use` 权重 | Apache-2.0 | live 模式，`REMBG_MODEL` 显式指定；**不用** rembg 默认的 BRIA RMBG-2.0（非商用） |
| 极限词表 | 自建 | — | `data/forbidden_words.txt`（44 词基础版，上线前按 1688 类目规则补全） |
| AI 隐式标识 | Pillow `PngInfo` 写 tEXt | — | `compose.save_png()`；M3 再升级到 C2PA（`c2pa-js`/`c2patool`） |
| 字体白名单 | 自建 | — | `data/fonts.whitelist.txt`；本机检测到 `MiSans-Regular.otf` 即通过 |
| 排版 / 编辑器 / 队列 | `vercel/satori`(MPL-2.0)、`konvajs/konva`、`timgit/pg-boss` | — | M2/M3 才引入，本骨架不装 |
| **只读思路，零代码** | `liangdabiao/ecom-details-image` | **无 LICENSE** | 1599 star 但法律上保留所有权利，**禁止复制任何代码** |

**必须自己写的六块**：模型适配层、商品事实结构化、四道合规校验、`design.json`、账本/存证、CDR 导出映射。这六块正是产品的护城河，抄不到也不该抄。

## 10 个环节

`读图剥 EXIF` → `事实校验` → `VL 看可见特征` → `文案` → `极限词拦截` → `抠图` → `AI 场景背景` → `合成三图+SVG` → `合规四件套+1688 图规` → `存证+三态交付`。

铁律：**facts 是人工填的硬事实，VL 只能补可见特征，不能覆盖；商品主体像素原样粘贴，AI 只动背景**（图实一致）。

## 产物结构

```
out/<tenant>/<sku>/
  final/main_white.png      第 1 张主图：白底、零文字、走硬校验
  final/scene.png           第 2 张：AI 场景 + 原主体
  final/detail.png          详情：文案 + 规格 + AI 显式标识
  editable/design.svg       文字未转曲，CorelDRAW 可直接打开精修
  evidence/generation_record.json   底图哈希、模型版本、prompt、校验、留存说明
  evidence/cost.json                成本账本（租户/单套口径预留）
  evidence/compliance_report.json  四件套报告
  evidence/AI_DISCLOSURE.txt       AI 生成内容披露
  design.json                      版本化回炉数据
  delivery.json                    READY / READY_PARTIAL / NEEDS_REVIEW
  work/                            中间产物，便于逐环节肉眼验收
```

## 已知边界

1. offline 的白底阈值抠图**只对白底不透明商品有效**；玻璃/反光杯必须用 live 的 `isnet-general-use` 或更好的模型，这正是 Stage A 要验证的生死线。
2. 1688 主图禁文字水印与《标识办法》要求的显式标识存在冲突；本骨架默认把显式标识放在详情图和披露文件、主图保持干净，**正式上架前必须按商家后台现行规则确认落位**。
3. 图规阈值（800×800、白底 98%、主体占比 60–94%、3MB）是可修改基线，不是平台最终规则。
4. 没有接对象存储、数据库、队列、鉴权——这些是 M3 的事，单图验证阶段刻意不做。
