"""模型适配层（薄适配器）：offline 全用本地桩，live 走供应商正式 API。

设计要点（对应架构报告 v2）：
  - 供应商、模型版本、地域、费用都从配置注入，切换国内/国际只改 .env，不改代码
  - 每次调用都记账；超时/未知状态记录为 UNKNOWN，绝不盲目重发（可能已计费）
  - 所有网络请求用标准库，offline 模式零联网、零依赖、零费用
"""
import base64
import io
import json
import time
import urllib.error
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# 保守估算单价（元），仅用于记账展示，以控制台账单为准
PRICE = {
    "qwen3-vl-plus": {"in": 1.0 / 1e6, "out": 10.0 / 1e6},
    "qwen-plus": {"in": 0.8 / 1e6, "out": 2.0 / 1e6},
    # qwen3.7-plus：实测该账号有 100 万免费额度，qwen-plus 本体没有
    "qwen3.7-plus": {"in": 0.8 / 1e6, "out": 2.0 / 1e6},
    "seedream-4-5-251128": {"image": 0.25},
    # 火山方舟国内版 Seedream 5.0（2026-11-22 官方价，1K 档）
    "doubao-seedream-5-0-flash-260915": {"image": 0.12},
    "doubao-seedream-5-0-pro-260628": {"image": 0.30},
    # 百炼 qwen-image 系列：该账号有 10 张/模型免费额度，实际现金成本由调用侧置 0
    "qwen-image-3.0": {"image": 0.30},
    "qwen-image-3.0-pro": {"image": 0.50},
}


class CallLedger:
    def __init__(self, cap_cny=10.0):
        self.calls = []
        self.cap = cap_cny

    def add(self, role, model, status, tokens_in=0, tokens_out=0,
            images=0, note="", cost_cny=None):
        if cost_cny is None:
            p = PRICE.get(model, {})
            cost_cny = round(tokens_in * p.get("in", 0)
                             + tokens_out * p.get("out", 0)
                             + images * p.get("image", 0), 4)
        self.calls.append(dict(role=role, model=model, status=status,
                               tokens_in=tokens_in, tokens_out=tokens_out,
                               images=images, cost_cny=cost_cny, note=note,
                               ts=time.strftime("%Y-%m-%dT%H:%M:%S%z")))

    @property
    def total(self):
        return round(sum(c["cost_cny"] for c in self.calls), 4)

    @property
    def over_cap(self):
        return self.total > self.cap


def _post(url, key, payload, timeout=90):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Adapter:
    def __init__(self, mode, env, ledger):
        self.mode = mode
        self.env = env
        self.ledger = ledger
        self.stub_used = []

    def _key(self, name):
        return (self.env.get(name) or "").strip()

    def _stub(self, role, what):
        self.stub_used.append(role)
        self.ledger.add(role, "local-stub", "STUB", note=what, cost_cny=0.0)

    # ---------- 1. 看懂商品 ----------
    def describe(self, image_path):
        if self.mode == "offline" or not self._key("DASHSCOPE_API_KEY"):
            self._stub("vision", "offline stub：未调用 VL，observed 为占位")
            return {"stub": True, "visible_features": ["杯身", "把手"],
                    "materials_guess": [], "logo_readable": None,
                    "deformation_risk": "unknown",
                    "note": "桩数据，不能用于判断还原度；填 DASHSCOPE_API_KEY 后自动切真实 VL"}
        key = self._key("DASHSCOPE_API_KEY")
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        payload = {
            "model": self.env.get("VL_MODEL", "qwen3-vl-plus"),
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": (
                    "只描述图片中可见的杯子特征，输出 JSON："
                    "visible_features, materials_guess, logo_readable, deformation_risk。"
                    "不要推测容量、尺寸、材质成分等不可见事实。")}]}],
        }
        try:
            d = _post(self.env.get("DASHSCOPE_BASE", "").rstrip("/") + "/chat/completions", key, payload)
            text = d["choices"][0]["message"]["content"]
            use = d.get("usage", {})
            self.ledger.add("vision", payload["model"], "OK",
                            use.get("prompt_tokens", 0), use.get("completion_tokens", 0))
            return {"stub": False, "raw": text}
        except Exception as e:
            # 超时/未知状态：可能已计费，记录 UNKNOWN 且不重发
            self.ledger.add("vision", payload["model"], "UNKNOWN", note=repr(e))
            return {"stub": False, "error": repr(e), "status": "UNKNOWN"}

    # ---------- 2. 套图文案 ----------
    def write_copy(self, facts):
        if self.mode == "offline" or not self._key("DASHSCOPE_API_KEY"):
            self._stub("copy", "offline stub：模板文案，未调用文本模型")
            return {"stub": True,
                    "title": f"{facts['name']} {facts['capacity_ml']}ml",
                    "slogan": "安心每一口",
                    "subtitle": f"{facts['material']} · {facts['color']}",
                    "bullets": [f"容量 {facts['capacity_ml']} ml",
                                f"材质 {facts['material']}",
                                f"颜色 {facts['color']}"],
                    "note": "桩文案，仅验证排版链路"}
        key = self._key("DASHSCOPE_API_KEY")
        payload = {
            "model": self.env.get("TEXT_MODEL", "qwen3.7-plus"),
            "messages": [
                {"role": "system", "content": (
                    "你是 1688 商品图文案助手。只能使用用户给出的事实，"
                    "禁止臆造参数，禁止使用绝对化用语（最/第一/国家级/100%等）。"
                    "输出 JSON: title（商品全称+规格）、slogan（10字以内营销口号，"
                    "朗朗上口、突出核心卖点）、subtitle（14字以内卖点短语）、bullets。")},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
        }
        try:
            d = _post(self.env.get("DASHSCOPE_BASE", "").rstrip("/") + "/chat/completions", key, payload)
            text = d["choices"][0]["message"]["content"]
            use = d.get("usage", {})
            self.ledger.add("copy", payload["model"], "OK",
                            use.get("prompt_tokens", 0), use.get("completion_tokens", 0))
            return {"stub": False, "raw": text}
        except Exception as e:
            self.ledger.add("copy", payload["model"], "UNKNOWN", note=repr(e))
            return {"stub": False, "error": repr(e), "status": "UNKNOWN"}

    # ---------- 3. 场景背景 ----------
    def generate_scene(self, prompt, size=(800, 800)):
        """双供应商：填了 BYTEPLUS_API_KEY 走 Seedream；否则用百炼 qwen-image。

        百炼路线 2026-11-06 已用真实 Key 联调通过（HTTP 200 / 1024x1024 / 免费额度）。
        只生成「空场景」，商品主体一律由 cutout() 抠出后本地合成，AI 不碰产品本身。
        """
        if self.mode == "offline":
            self._stub("scene", "offline stub：程序化渐变背景，未调用生图模型")
            return self._procedural_scene(size)
        provider = (self.env.get("SCENE_PROVIDER") or "auto").strip().lower()
        has_byteplus = bool(self._key("BYTEPLUS_API_KEY"))
        has_dashscope = bool(self._key("DASHSCOPE_API_KEY"))
        if provider == "byteplus" or (provider == "auto" and has_byteplus):
            return self._scene_byteplus(prompt, size)
        if provider in ("dashscope", "auto") and has_dashscope:
            return self._scene_dashscope(prompt, size)
        self._stub("scene", "未配置任何生图 Key：程序化渐变背景（不冒充真实生图）")
        return self._procedural_scene(size)

    @staticmethod
    def _extract_image(d):
        """兼容 OpenAI 风格 data[0].url / b64_json 与 DashScope 风格 output.results[0].url。"""
        import base64 as _b64
        for item in (d.get("data") or []):
            if item.get("b64_json"):
                raw = _b64.b64decode(item["b64_json"])
                return Image.open(io.BytesIO(raw)).convert("RGB"), raw
        urls = [i.get("url") for i in (d.get("data") or []) if i.get("url")]
        if not urls:
            results = ((d.get("output") or {}).get("results") or [])
            urls = [i.get("url") for i in results if i.get("url")]
        if not urls:
            raise ValueError("响应中没有图片 URL 或 b64_json：" + json.dumps(d, ensure_ascii=False)[:200])
        with urllib.request.urlopen(urls[0], timeout=120) as r:
            raw = r.read()
        return Image.open(io.BytesIO(raw)).convert("RGB"), raw

    def _scene_byteplus(self, prompt, size):
        """火山方舟 / BytePlus 通用生图：size 用 1K/1.5K/2K 档位，不是像素串。

        2026-11-22 切到火山方舟国内版 Seedream 5.0 flash（0.12 元/张）。
        """
        model = self.env.get("SEEDREAM_MODEL", "doubao-seedream-5-0-flash-260915")
        full_prompt = (prompt + " 画面中不要出现任何商品、杯子、瓶罐、文字、logo、人物或水印，"
                       "中央留出大面积干净留白用于后期合成商品。")
        payload = {"model": model, "prompt": full_prompt,
                   "size": self.env.get("SEEDREAM_SIZE", "1K"),
                   "watermark": False}
        url = self.env.get("BYTEPLUS_BASE", "").rstrip("/") + "/images/generations"
        try:
            d = _post(url, self._key("BYTEPLUS_API_KEY"), payload, timeout=180)
            img, _ = self._extract_image(d)
            self.ledger.add("scene", model, "OK", images=1,
                            note="火山方舟 Seedream；" + str(d.get("usage", {}))[:160])
            return img.resize(size, Image.LANCZOS)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            self.ledger.add("scene", model, "FAIL", note=f"HTTP {e.code}: {body}")
            return self._procedural_scene(size, fallback=True)
        except Exception as e:
            # 超时/未知状态可能已计费，记 UNKNOWN 且不重发
            self.ledger.add("scene", model, "UNKNOWN", note=repr(e))
            return self._procedural_scene(size, fallback=True)

    def _scene_dashscope(self, prompt, size):
        model = self.env.get("IMAGE_MODEL", "qwen-image-3.0")
        # OpenAI 兼容模式 size 必须用字母 x，且不传 response_format（传了也被忽略）
        payload = {
            "model": model,
            "prompt": (prompt + " 画面中不要出现任何商品、杯子、瓶罐、文字、logo、人物或水印，"
                       "中央留出大面积干净留白用于后期合成商品。"),
            "negative_prompt": "杯子, 水杯, 瓶, 商品, 文字, 字幕, logo, 水印, 人物, 畸变, 杂乱",
            "size": "1024x1024", "n": 1, "watermark": False,
        }
        try:
            d = _post(self.env.get("DASHSCOPE_BASE", "").rstrip("/") + "/images/generations",
                      self._key("DASHSCOPE_API_KEY"), payload, timeout=600)
            img, raw = self._extract_image(d)
            # 免费额度内现金成本为 0；额度耗尽后按控制台账单另计
            self.ledger.add("scene", model, "OK", images=1, cost_cny=0.0,
                            note="百炼免费额度（已开用完即停）；" + str(d.get("usage", {}))[:160])
            return img.resize(size, Image.LANCZOS)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            self.ledger.add("scene", model, "FAIL", note=f"HTTP {e.code}: {body}")
            return self._procedural_scene(size, fallback=True)
        except Exception as e:
            self.ledger.add("scene", model, "UNKNOWN", note=repr(e))
            return self._procedural_scene(size, fallback=True)

    @staticmethod
    def _procedural_scene(size=(800, 800), fallback=False):
        w, h = size
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        top = np.array([236, 240, 245]); bottom = np.array([206, 218, 230])
        for y in range(h):
            arr[y, :, :] = (top * (1 - y / h) + bottom * (y / h)).astype(np.uint8)
        img = Image.fromarray(arr, "RGB")
        d = ImageDraw.Draw(img)
        d.rectangle([0, int(h * 0.68), w, h], fill=(222, 214, 203))
        d.ellipse([int(w * 0.08), int(h * 0.06), int(w * 0.5), int(h * 0.5)],
                  fill=(250, 246, 235))
        return img.filter(ImageFilter.GaussianBlur(18))

    # ---------- 3b. 场景图生图（指令编辑直出，2026-11-24 实验定调） ----------
    # 2026-11-24 风格化：单一「米色亚麻暖光」提示词被用户判定太平淡/太复古，
    # 参考样张（IBL 儿童杯 3D 卡通渲染风）定调后改为多风格预设，默认 candy3d。
    I2I_STYLES = {
        "candy3d": (
            "把纯白背景替换为3D卡通渲染风格的电商场景（C4D质感）：明黄色和奶油色的"
            "圆润几何展台、圆弧拱门、波浪软垫等玩具感道具，背景墙是柔和的糖果色渐变"
            "（明黄、粉紫、嫩绿），色彩明快鲜艳饱和，柔和均匀的棚拍灯光，"
            "商品底部有柔和的接触阴影，整体像儿童保温杯电商主图的场景。"
            "商品保持原样不动，不要改变商品本身的形状、颜色、图案、文字、Logo。"
            "画面中不要出现任何文字、水印。"),
        "warm": (
            "把纯白背景替换为柔和温暖的摄影棚台面场景：米色亚麻桌布、左上方柔和自然光、"
            "浅景深、背景有虚化的暖色装饰，商品保持原样不动，商品底部有自然的接触阴影，"
            "整体像真实拍摄的商品图。不要改变商品本身的形状、颜色、图案、文字、Logo。"),
        "vibrant": (
            "把纯白背景替换为明亮绚丽的电商主图场景：高饱和渐变色幕布（珊瑚橙到蜜桃粉），"
            "大面积柔和彩色光晕、悬浮光斑与细小粒子点缀，同色系圆润台面，通透干净，"
            "商品保持原样不动，商品底部有柔和的接触阴影。"
            "不要改变商品本身的形状、颜色、图案、文字、Logo。画面中不要出现任何文字、水印。"),
        "premium_dark": (
            "把纯白背景替换为深色高级感商业摄影场景：深灰黑渐变幕布、一束聚光灯从左上方"
            "打下、镜面反光台面带清晰倒影、细碎金色光斑点缀，商业大片质感，"
            "商品保持原样不动，商品底部有自然的接触阴影。"
            "不要改变商品本身的形状、颜色、图案、文字、Logo。画面中不要出现任何文字、水印。"),
    }
    # 兼容旧引用（Stage A 存档口径 = warm）
    I2I_PROMPT = I2I_STYLES["warm"]

    def edit_scene(self, source_img, size=(800, 800), product_rgba=None, style="candy3d"):
        """图生图直出：整张定稿图交给 Seedream 做指令编辑。

        与 generate_scene（空场景 + 本地贴图合成）互斥。实测（2026-11-24）：
        融合效果显著更好，但模型会重构图（缩放/位移），所以必须配合
        compliance.check_scene_shape 的 bbox 对齐 IoU 门禁。
        style 取 I2I_STYLES 键（candy3d/warm/vibrant/premium_dark），未知值回退 warm。
        product_rgba 仅供 offline 桩使用（live 忽略，真实调用发整张白底图）。
        返回 (合成场景图 RGB, info dict)；失败抛异常，由调用方决定降级路线。
        """
        if self.mode == "offline":
            self._stub("scene", "offline stub：i2i 桩 = 程序化背景 + 桩主体合成（模拟直出形态）")
            product = (product_rgba or source_img).convert("RGBA")
            canvas = self._procedural_scene(size).convert("RGBA")
            scaled = product.resize((int(size[0] * 0.62), int(size[1] * 0.62)), Image.LANCZOS)
            x = (size[0] - scaled.width) // 2
            y = (size[1] - scaled.height) // 2
            canvas.alpha_composite(scaled, (x, y))
            cut_full = Image.new("RGBA", size, (0, 0, 0, 0))   # 桩输出主体（透明底全帧）
            cut_full.alpha_composite(scaled, (x, y))
            info = {"flow": "stub", "cutout": cut_full,
                    "note": "桩合成，主体位置已知，仅用于离线验证门禁计算"}
            return canvas.convert("RGB"), info
        provider = (self.env.get("SCENE_PROVIDER") or "auto").strip().lower()
        has_byteplus = bool(self._key("BYTEPLUS_API_KEY"))
        if provider not in ("byteplus", "auto") or not has_byteplus:
            raise RuntimeError("i2i 直出需要火山方舟 BYTEPLUS_API_KEY（当前未配置或 SCENE_PROVIDER 指向百炼）")
        model = self.env.get("SEEDREAM_MODEL", "doubao-seedream-5-0-flash-260915")
        prompt = self.I2I_STYLES.get(style, self.I2I_PROMPT)
        buf = io.BytesIO()
        source_img.convert("RGB").save(buf, "PNG")
        payload = {"model": model, "prompt": prompt,
                   "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
                   "response_format": "url", "size": "1K", "watermark": False}
        url = self.env.get("BYTEPLUS_BASE", "").rstrip("/") + "/images/generations"
        try:
            d = _post(url, self._key("BYTEPLUS_API_KEY"), payload, timeout=300)
            img, _ = self._extract_image(d)
            self.ledger.add("scene", model, "OK", images=1,
                            note="i2i 指令编辑直出（Seedream image 参数）；" + str(d.get("usage", {}))[:160])
            info = {"flow": "live", "model": model,
                    "style": style, "prompt": prompt, "seed": payload.get("seed")}
            return img.resize(size, Image.LANCZOS), info
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            self.ledger.add("scene", model, "FAIL", note=f"i2i HTTP {e.code}: {body}")
            raise RuntimeError(f"i2i 生图失败 HTTP {e.code}: {body}")
        except Exception as e:
            # 超时/未知状态可能已计费，记 UNKNOWN 且不重发同一请求
            self.ledger.add("scene", model, "UNKNOWN", note="i2i " + repr(e))
            raise

    # ---------- 4. 抠图（保留商品主体） ----------
    def cutout(self, img):
        if self.mode == "offline":
            self._stub("cutout", "offline stub：白底阈值抠图（仅对白底不透明商品有效）")
            rgb = np.asarray(img.convert("RGB")).astype(np.int16)
            dist = 255 - rgb.min(axis=2)
            alpha = np.where(dist > 14, 255, 0).astype(np.uint8)
            rgba = img.convert("RGBA")
            rgba.putalpha(Image.fromarray(alpha, "L").filter(ImageFilter.GaussianBlur(0.6)))
            return rgba, "white-threshold"
        # live：显式指定 Apache-2.0 的 isnet-general-use，不用 rembg 默认的
        # u2netp / BRIA RMBG-2.0（后者为非商用许可，且玻璃杯效果差）
        try:
            from rembg import new_session, remove
            model = self.env.get("REMBG_MODEL", "isnet-general-use")
            session = new_session(model)
            out = remove(img.convert("RGBA"), session=session, alpha_matting=True,
                         alpha_matting_foreground_threshold=240,
                         alpha_matting_background_threshold=15)
            self.ledger.add("cutout", model, "OK", note="local CPU, 0 元")
            return out, model
        except Exception as e:
            self.ledger.add("cutout", "rembg", "UNAVAILABLE", note=repr(e))
            raise RuntimeError(f"live 抠图不可用（pip install 'rembg[cpu]' onnxruntime）：{e}")
