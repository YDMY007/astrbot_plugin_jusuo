from __future__ import annotations

import asyncio
import json
import textwrap
import ssl
import os
import time
import tempfile
import base64
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import aiohttp  # type: ignore[import-untyped]

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult  # type: ignore[import-untyped]
from astrbot.api.star import Context, Star  # type: ignore[import-untyped]
from astrbot.api import logger  # type: ignore[import-untyped]
from astrbot.api.web import error_response, json_response, request

try:
    from astrbot.api.provider import AstrBotConfig
except ImportError:
    try:
        from astrbot.api.all import AstrBotConfig
    except ImportError:
        AstrBotConfig = type("AstrBotConfig", (), {})

# 状态指令图片内嵌字体（子集化），避免无头 Chromium 缺中文字体/emoji 字体出现方块
try:
    from .font_embed import status_font_face_css
except Exception:
    try:
        from font_embed import status_font_face_css
    except Exception:
        def status_font_face_css() -> str:
            return ""

# ===================== 数据源1: jusuo.playmmo.cn (Supabase) =====================
SOURCE1_NAME = "居所站"
DEFAULT_SUPABASE_URL = "https://dtwqqcetisagubdwwdtf.supabase.co"
DEFAULT_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR0d3FxY2V0aXNhZ3ViZHd3ZHRmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM0NDAwMDEsImV4cCI6MjA5OTAxNjAwMX0."
    "f6Wc4eCj_m4NpwfjnpTfWO0ZeuvXCcJ-agDFP3bJ5ro"
)
TABLE_RESIDENCE = "residence_entries"
TABLE_RANCH = "ranch_entries"
TABLE_RANCH_PRESETS = "ranch_product_presets"
TABLE_FURNITURE = "furniture_entries"
TABLE_PARTNER = "partner_wall"
TABLE_TEMPLATE = "template_entries"
TABLE_UNIT_PRICES = "unit_prices"
# 默认播报阈值：每个作物的百工币阈值
DEFAULT_POLL_THRESHOLDS: dict[str, int] = {
    "炎霞辣椒": 500_000,
    "灿金云棉": 1_000_000,
    "曳紫云棉": 2_000_000,
    "旭日辣椒": 3_000_000,
    "胭纱云棉": 4_000_000,
    "星夜龙眼": 6_500_000,
    "蝶影莲子": 8_000_000,
}
# 网站一 public-query Edge Function（主数据查询）
SOURCE1_API = f"{DEFAULT_SUPABASE_URL}/functions/v1/public-query"
DEFAULT_SOURCE1_API_KEY = ""

# ===================== 数据源2: hokshijie.online =====================
SOURCE2_NAME = "HOK站"
HOK_API_BASE = "https://hokshijie.online:5000"

# ===================== 数据源3: wsjjiayuan.cn =====================
SOURCE3_NAME = "家园站"
WSJJ_API_BASE = "https://wsjjiayuan.cn"

# ===================== 通用数据 =====================
KNOWN_CROPS = [
    "炎霞辣椒", "灿金云棉", "曳紫云棉", "旭日辣椒",
    "胭纱云棉", "星夜龙眼", "蝶影莲子",
]
KNOWN_MERCHANTS = ["芍药", "紫翠", "虎头", "金靡", "鱼丞相"]

# 商人家具本地缓存：{商人名: {品质: [家具列表]}}
MERCHANT_FURNITURE_MAP: dict[str, dict[str, list[str]]] = {
    "芍药": {
        "紫色品质": ["幻纱莲花", "魔道莲花", "双色紫藤木", "小型迎客松"],
        "蓝色品质": ["白色雏菊", "金鸡雏菊", "成年粉樱", "粉樱华年", "大木篱怪木", "小木篱怪木",
                    "黄秋英", "金枝黄叶树", "君子兰", "千禧花", "牵牛花", "探首迎客松",
                    "迎宾松木", "羽扇蓝", "紫罗兰"],
    },
    "紫翠": {
        "紫色品质": ["青铜立面灯", "三足莲凳", "瑶台镜", "云芽灯", "紫藤花秋千"],
        "蓝色品质": ["餐具组合", "茶点组合", "蝶梦地毯", "寒星地毯", "墨蝶地毯", "花临案",
                    "幻梦如旧", "毛茸茸冰糕", "窃蓝瓶", "图纸：窃蓝瓶", "烧炉", "夜雨几", "一方几"],
    },
    "虎头": {
        "紫色品质": ["贝壳立柱", "蝶镂石", "蝶使木雕", "小蝶使木雕", "精致辎车", "巨型气球",
                    "聆梦台", "青铜巨像丙", "青铜巨像甲", "青铜巨像乙", "山月屏风", "扇形屏风", "紫韵屏风"],
        "蓝色品质": ["幻梦屏风", "妄梦几"],
    },
    "金靡": {
        "紫色品质": ["东方曜立牌", "老夫子立牌", "李白立牌", "鲁班惊喜箱", "鲁班立牌",
                    "蒙犽惊喜箱", "蒙犽立牌", "墨子立牌", "孙膑惊喜箱", "孙膑立牌",
                    "西施惊喜箱", "西施立牌", "曜惊喜箱"],
        "蓝色品质": ["东方曜海报", "东方曜招牌", "海报・蒙犽", "鲁班海报", "孙膑海报",
                    "西施海报", "庄周招牌", "木制谱架"],
    },
    "鱼丞相": {
        "紫色品质": ["咕呱龛座"],
        "蓝色品质": ["遨梦石斑鱼", "碧玺灵鱼", "沧驳龙鱼", "潮波灵鱼", "翠璃斗鱼", "黛蓝斗鱼",
                    "靛蓝龙鱼", "枫华斗鱼", "绀珠石斑鱼", "褐斑龙鱼", "焕尾斗鱼", "辉彤灵鱼",
                    "金银灵鱼", "堇华石斑鱼", "锦葵龙鱼", "枯荣龙鱼", "黎浪灵鱼", "鎏金龙鱼",
                    "梦溪灵鱼", "翩若灵鱼", "清水龙鱼", "听灵龙鱼", "嫣红斗鱼", "邀梦石斑鱼",
                    "荧裳石斑鱼", "愈心灵鱼", "橙鱼挂饰", "绿鱼挂饰", "青鱼挂饰", "除噩雷鱼",
                    "咕呱神龛", "梦境庭灯", "学院庭灯", "深色蕨类", "石像丙", "石像甲",
                    "石像乙", "铜制香炉", "小型卷轴桶", "幽梦"],
        "绿色品质": ["浅色蕨类", "青石庭灯", "室内吊灯", "营地吊灯", "营地提灯", "朱红地毯", "装饰编篓"],
    },
}
# 从本地缓存提取全部家具名（供匹配/列表展示）
_ALL_FURNITURE_NAMES: list[str] = sorted(
    set(fname for m in MERCHANT_FURNITURE_MAP.values() for names in m.values() for fname in names),
    key=len, reverse=True,
)

# 白名单关键词：所有作物名 + 商人，在白名单群内触发自动回复
WHITELIST_KEYWORDS = KNOWN_CROPS + ["商人"]




class JusuoPlugin(Star):
    """王世杰居所助手 — 双数据源"""

    async def initialize(self, event=None):
        """插件初始化"""
        pass

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config  # 保留配置引用，供指令修改后回写 WebUI
        import time as _time
        self.supabase_url = DEFAULT_SUPABASE_URL
        self.anon_key = DEFAULT_ANON_KEY
        self.hok_api = HOK_API_BASE
        self.wsjj_api = WSJJ_API_BASE
        self.source1_api_key = DEFAULT_SOURCE1_API_KEY
        self._warned_empty_api_key: bool = False  # 空密钥警告仅打印一次
        self.enable_source1 = True
        self.enable_source2 = True
        self.enable_source3 = True
        self.hok_items_limit: int = 200
        self._unit_prices_cache: dict = {}
        self._ranch_products_cache: dict = {}
        self._ranch_product_names: list[str] = []
        self._furniture_names: list[str] = []
        self._cache_time: float = 0
        # 源1 API 短期缓存 & 频率控制（200次/小时限流保护）
        self._source1_result_cache: dict = {}  # {cache_key: (data, timestamp)}
        self._source1_cache_ttl: float = 60.0   # 缓存60秒
        self._source1_last_call: float = 0.0
        self._source1_min_interval: float = 0.5  # 两次请求最小间隔0.5秒
        self.polling_enabled: bool = False
        self.poll_interval_minutes: int = 3
        self._polling_task: Optional[asyncio.Task] = None
        # QQ级查询频率限制（10分钟3次，管理员豁免）
        self._qq_query_timestamps: dict[str, list[float]] = {}
        self._qq_rate_limit_window: float = 600.0  # 10分钟
        self._qq_rate_limit_max: int = 3
        self._reported_2x_crops: set[str] = set()  # 已播报过的作物，避免重复播报
        # 数据目录：使用 AstrBot 规范的插件数据目录（data/plugin_data/<name>/，独立于插件代码目录）
        # 更新/重装插件时不会清空该目录，查询统计等持久化数据得以保留
        self._data_dir = self._resolve_data_dir()
        # 持久化播报状态文件路径（插件重载后恢复，避免重复播报）
        self._poll_state_file = self._data_dir / "_poll_state.json"
        # 历史最高价记录（key=crop_name），由轮询高价自动更新并持久化
        self._high_records_file = self._data_dir / "_high_records.json"
        self._high_records: dict[str, dict] = {}
        # 作物查询次数统计（持久化），自本版日期起计数
        # 结构：{ "total": {crop: n}, "daily": {date: {crop: n}}, "weekly": {week: {crop: n}} }
        self._crop_query_counts_file = self._data_dir / "_crop_query_counts.json"
        self._crop_query_counts: dict = {
            "total": {},
            "daily": {},
            "weekly": {},
        }
        # 「已录入数据」统计：跨三站按 uid 去重，每 7 天窗口每 uid 计 1 次记录，累计持久化
        # 数据自 version_date 起计算，不补旧；结构 {start_date, last_compute, uids:{uid:[period,...]}}
        self._录入_file = self._data_dir / "_录入_records.json"
        self._录入_records: dict = {"start_date": "2026-07-12", "last_compute": 0.0, "uids": {}}
        # 若旧版本把数据写在插件目录内，迁移到规范数据目录（仅当新位置尚无数据时）
        self._migrate_legacy_data(self._data_dir)
        self.version_date = "2026-07-12"  # 统计起始日期（自本版生效，不补旧数据）
        self._poll_thresholds: dict[str, int] = {}  # 每个作物的播报阈值（百工币）
        self.poll_crop_filter: set[str] = set(KNOWN_CROPS)  # 轮询播报作物勾选（默认全选）
        self.whitelist_groups: set[str] = set()
        self.admin_qqs: set[str] = set()
        self.custom_reply: str = ""
        self.whitelist_crop_detect: bool = True
        self.whitelist_at_reply: bool = True
        self.whitelist_merchant_reply: bool = True
        self.recall_seconds: int = 30  # 查询结果自动撤回秒数（0=不撤回）
        # 群独立设置 {group_id: {crop_detect, at_reply, merchant_reply}}
        self._group_settings: dict[str, dict] = {}

        if config:
            self.supabase_url = config.get("supabase_url", DEFAULT_SUPABASE_URL).rstrip("/")
            # 防御性修正：用户可能在配置里把 supabase_url 误填成 public-query 函数地址
            # （如 .../functions/v1/public-query），会导致 /rest/v1/<table> 请求误打到该函数而返回 400。
            # 这里统一截掉函数路径后缀，保证 REST 与 public-query 都能正确拼接。
            for _suffix in ("/functions/v1/public-query", "/functions/v1"):
                if self.supabase_url.endswith(_suffix):
                    self.supabase_url = self.supabase_url[: -len(_suffix)].rstrip("/")
                    break
            _anon_cfg = config.get("supabase_anon_key", "")
            # 配置为空（默认/未填）时回退内置默认密钥；schema 设计意图：留空=使用内置默认密钥
            self.anon_key = _anon_cfg.strip() if _anon_cfg and _anon_cfg.strip() else DEFAULT_ANON_KEY
            self.hok_api = config.get("hok_api_url", HOK_API_BASE).rstrip("/")
            self.wsjj_api = config.get("wsjj_api_url", WSJJ_API_BASE).rstrip("/")
            self.source1_api_key = config.get("source1_api_key", DEFAULT_SOURCE1_API_KEY)
            self.enable_source1 = config.get("enable_source1", True)
            self.enable_source2 = config.get("enable_source2", True)
            self.enable_source3 = config.get("enable_source3", True)
            self.hok_items_limit = int(config.get("hok_items_limit", 200))
            self.polling_enabled = config.get("polling_enabled", False)
            self.poll_interval_minutes = max(1, int(config.get("poll_interval_minutes", 3)))
            # 读取轮播作物勾选
            poll_crops = set()
            for crop in KNOWN_CROPS:
                key = f"poll_crop_{crop}"
                if config.get(key, True):
                    poll_crops.add(crop)
            self.poll_crop_filter = poll_crops if poll_crops else set(KNOWN_CROPS)
            admin_str = config.get("admin_qqs", "")
            if admin_str:
                admin_str = str(admin_str).replace("，", ",")
                self.admin_qqs = {a.strip() for a in admin_str.split(",") if a.strip()}
            self.custom_reply = config.get("custom_reply", "")
            self.whitelist_crop_detect = config.get("whitelist_crop_detect", True)
            self.whitelist_at_reply = config.get("whitelist_at_reply", True)
            self.whitelist_merchant_reply = config.get("whitelist_merchant_reply", True)
            self.recall_seconds = int(config.get("recall_seconds", 30))

            # 从5个群槽位读取独立配置（新 object 结构优先，旧 key 回退兼容迁移）
            self._group_settings = {}
            self.whitelist_groups = set()
            migrated_count = 0
            for i in range(1, 6):
                # 优先读新 object 结构 group_config_i
                gc = config.get(f"group_config_{i}", {}) or {}
                gid = str(gc.get("group_id", "") or "").strip() if isinstance(gc, dict) else ""
                # 新结构为空 → 回退旧 key（兼容旧版配置迁移）
                if not gid:
                    gid = str(config.get(f"group{i}_id", "") or "").strip()
                    if gid:
                        migrated_count += 1
                if not gid:
                    continue

                # 作物列表：新结构 crops(list) 优先，回退旧 7 个 bool 勾选
                crops_raw = gc.get("crops") if isinstance(gc, dict) else None
                if isinstance(crops_raw, list) and crops_raw:
                    poll_crops = [c for c in KNOWN_CROPS if c in crops_raw]
                else:
                    # 旧结构：7 个 group{i}_crop_{作物} bool
                    poll_crops = [
                        crop for crop in KNOWN_CROPS
                        if config.get(f"group{i}_crop_{crop}", True)
                    ]
                if not poll_crops:
                    poll_crops = list(KNOWN_CROPS)

                # 各开关：新 object 优先，回退旧 key
                def _gopt(key_new, key_old, default=True):
                    if isinstance(gc, dict) and key_new in gc:
                        return bool(gc.get(key_new, default))
                    return bool(config.get(key_old, default))

                settings = {
                    "crop_detect": _gopt("crop_detect", f"group{i}_crop_detect"),
                    "at_reply": _gopt("at_reply", f"group{i}_at_reply"),
                    "merchant_reply": _gopt("merchant_reply", f"group{i}_merchant_reply"),
                    "custom_reply": str((gc.get("custom_reply") if isinstance(gc, dict) else None) or config.get(f"group{i}_custom_reply", "") or ""),
                    "polling_enabled": _gopt("polling_enabled", f"group{i}_polling_enabled"),
                    "enable_source1": _gopt("enable_source1", f"group{i}_enable_source1"),
                    "enable_source2": _gopt("enable_source2", f"group{i}_enable_source2"),
                    "enable_source3": _gopt("enable_source3", f"group{i}_enable_source3"),
                    "poll_crops": poll_crops,
                }
                self._group_settings[gid] = settings
                self.whitelist_groups.add(gid)
            if migrated_count > 0:
                logger.info(f"[居所] 检测到 {migrated_count} 个群使用旧版配置结构，已自动兼容读取。建议在 WebUI 用新折叠界面重新确认并保存一次配置")
            # 读取每个作物的播报阈值
            self._poll_thresholds = {}
            for crop in KNOWN_CROPS:
                key = f"poll_threshold_{crop}"
                self._poll_thresholds[crop] = int(config.get(key, DEFAULT_POLL_THRESHOLDS.get(crop, 9_990_000)))
            logger.info(f"[居所] 配置加载：白名单群={self.whitelist_groups}，管理员QQ={self.admin_qqs}，作物检测={self.whitelist_crop_detect} @回复={self.whitelist_at_reply} 商人回复={self.whitelist_merchant_reply}")
            if self.enable_source1 and not self.anon_key:
                self._warned_empty_api_key = True
                logger.warning("[居所] ⚠️ 数据源1 Supabase anon_key 未配置，请在WebUI中设置")

        # 恢复已播报状态（防止重载后重复播报）
        self._load_poll_state()
        # 恢复历史最高价记录
        self._load_high_records()
        self._load_crop_query_counts()
        self._load_录入_records()

        # 异步加载牧场产品名缓存
        asyncio.ensure_future(self._load_ranch_presets())

        # 启动即计算「已录入数据」统计（后台，不阻塞）
        try:
            asyncio.ensure_future(self._compute_录入_data())
        except Exception as e:
            logger.warning(f"[居所] 启动计算已录入数据失败: {e}")

        # 启动后台轮询
        self._start_background_polling()

        # 注册插件页面 Web API（pages/dashboard 前端通过 bridge 调用）
        self._register_page_apis(context)

        # SnowLuma 群聊换行全局修复（拦截所有插件的 plain_result）
        self._snowluma_fix = config.get("snowluma_newline_fix", False) if config else False
        if self._snowluma_fix:
            self._install_snowluma_fix()

    # ==================== SnowLuma 群聊换行全局修复 ====================

    def _install_snowluma_fix(self):
        """包装 filter.command/regex handler 生成器，群聊含\\n 消息走 adapter 直发"""
        try:
            plugin_self = self
            _cached_adapter = None

            def _find_adapter(event_instance):
                nonlocal _cached_adapter
                if _cached_adapter is not None:
                    return _cached_adapter
                for src in (getattr(event_instance, 'message_obj', None), event_instance):
                    if src is None:
                        continue
                    for attr_name in ('_adapter', 'adapter', '_bot', 'bot', '_client', 'client', '_platform', 'platform'):
                        val = getattr(src, attr_name, None)
                        if val and hasattr(val, 'api') and hasattr(val.api, 'send_group_msg'):
                            _cached_adapter = val
                            return val
                mgr = getattr(plugin_self.context, 'platform_manager', None)
                if mgr:
                    platforms = None
                    for method in ('get_platforms', 'get_instances', 'platforms', 'get_all_platforms'):
                        val = getattr(mgr, method, None)
                        if callable(val):
                            try:
                                platforms = val()
                            except Exception:
                                continue
                        elif isinstance(val, (list, dict)):
                            platforms = val
                        if platforms:
                            break
                    if platforms:
                        if isinstance(platforms, dict):
                            platforms = platforms.values()
                        for plat in platforms:
                            adapter = getattr(plat, 'adapter', None) or getattr(plat, 'bot', None) or getattr(plat, 'client', None)
                            if adapter and hasattr(adapter, 'api') and hasattr(adapter.api, 'send_group_msg'):
                                _cached_adapter = adapter
                                return adapter
                return None

            async def _send_via_adapter(gid: str, text: str, adapter):
                payload = []
                for chunk in text.split("\n"):
                    if payload:
                        payload.append({"type": "text", "data": {"text": "\n"}})
                    payload.append({"type": "text", "data": {"text": chunk}})
                await adapter.api.send_group_msg(group_id=self._to_group_id(gid), message=payload)

            async def _try_redirect(event_instance, result_text: str) -> bool:
                """尝试用 adapter 直发，成功返回 True"""
                gid = plugin_self._get_group_id(event_instance)
                if not gid:
                    return False
                adapter = _find_adapter(event_instance)
                if not adapter:
                    return False
                try:
                    await _send_via_adapter(gid, result_text, adapter)
                    return True
                except Exception as e:
                    logger.debug(f"[居所] SnowLuma 修复直发失败：{e}")
                    return False

            # 包装 AstrMessageEvent.plain_result，标记已拦截的文本
            self._snowluma_original_plain_result = AstrMessageEvent.plain_result
            _original_plain_result = self._snowluma_original_plain_result

            def _fixed_plain_result(self, text):
                """全局拦截：QQ 群含 \\n 消息走 adapter 直发，微信等平台正常走管道"""
                if isinstance(text, str) and '\n' in text:
                    gid = plugin_self._get_group_id(self)
                    if gid and gid.isdigit():
                        adapter = _find_adapter(self)
                        if adapter:
                            import asyncio
                            try:
                                loop = asyncio.get_running_loop()
                                loop.create_task(_try_redirect(self, text))
                                # 返回空消息阻止正常管道发送
                                return _original_plain_result(self, "")
                            except RuntimeError:
                                pass
                return _original_plain_result(self, text)

            AstrMessageEvent.plain_result = _fixed_plain_result

            # 包装本插件的所有 handler 生成器（跳过生命周期方法）
            import types
            _LIFECYCLE_SKIP = {'initialize', 'terminate'}
            for attr_name in list(dir(plugin_self.__class__)):
                if attr_name.startswith('_') or attr_name in _LIFECYCLE_SKIP:
                    continue
                val = getattr(plugin_self.__class__, attr_name, None)
                if not callable(val):
                    continue
                try:
                    original = getattr(plugin_self, attr_name)
                except Exception:
                    continue
                if not callable(original):
                    continue
                # 仅包装异步生成器 handler，非生成器直接跳过
                import inspect as _inspect
                if not _inspect.isasyncgenfunction(original) and not _inspect.iscoroutinefunction(original):
                    continue

                def _make_wrapper(orig_handler, name):
                    async def wrapper(event, *args, **kwargs):
                        gen = orig_handler(event, *args, **kwargs)
                        async for result in gen:
                            snow_text = getattr(result, '_snowluma_text', None) if result is not None else None
                            if snow_text and isinstance(snow_text, str) and '\n' in snow_text:
                                redirected = await _try_redirect(event, snow_text)
                                if redirected:
                                    continue  # 跳过此 yield，已由 adapter 发送
                            yield result
                    wrapper.__name__ = name
                    wrapper.__qualname__ = f"{plugin_self.__class__.__name__}.{name}"
                    return wrapper

                setattr(plugin_self, attr_name, _make_wrapper(original, attr_name))

            logger.info("[居所] SnowLuma 群聊换行修复已启用（handler 生成器包装）")
        except Exception as e:
            logger.error(f"[居所] SnowLuma 修复安装失败：{e}")

    # ==================== 命令 ====================

    @filter.command_group("jusuo")
    def jusuo_group(self):
        pass

    @filter.command("帮助")
    async def cmd_help(self, event: AstrMessageEvent):
        admin_lines = ""
        if self._is_admin(event):
            admin_lines = "\n🔧 管理员：自定义回复 <内容>  ·  设置 <作物> 阈值 <数字>  ·  设置撤回 <秒数>"
        text = textwrap.dedent(f"""
        🌾 王世杰居所助手
        📖 帮助 · 📋 状态

        📡 数据源：酸奶很忙 五河道士哟

        🔍 查询指令
          🌿 高倍 <作物>    🔍 搜索 <商人>
          🐄 牧场 <产品>    🪑 家具 <家具>
          💬 交友墙         🏗️ 模板

        🔧 工具：🔥刷二  🔔播报开关  🔍检测开关  📊查询统计

        🌿 全部作物（{len(KNOWN_CROPS)}种）
          发送「居所」查看完整列表

        🐄 全部牧场产品（{len(getattr(self, '_ranch_product_names', []))}种）
          发送「居所」查看完整列表

        🪑 全部家具  发送「家具」查看

        🔗 github.com/YDMY007/astrbot_plugin_jusuo
        """).strip() + admin_lines
        async for m in self._send_result(event, text):
            yield m

    @filter.command("居所")
    async def cmd_jusuo(self, event: AstrMessageEvent):
        """查看插件全部使用指令：作用、用法与权限标注"""
        await self._ensure_ranch_products()
        text = textwrap.dedent("""\
        🌾 王世杰居所助手 · 指令总览
        权限：[全员] 所有人 · [管理员] 仅群管理

        ━━━━ 查询 · 全员 ━━━━
        ▸ 高倍 <作物>｜高价收购查询（例：高倍 蝶影莲子）
        ▸ <作物>｜直接发作物名即可查询
        ▸ 搜索 <商人>｜按商人查收购 / 家具 / 分享
        ▸ 商人｜查看已知商人列表
        ▸ 牧场 <产品>｜牧场产品分享（无参列出可查项）
        ▸ 家具 <家具>｜家具分享（无参生成图鉴）
        ▸ 交友墙｜最新 5 条搭子交友墙
        ▸ 模板｜热门建造模板 TOP 5

        ━━━━ 工具与状态 · 全员 ━━━━
        ▸ 刷二｜手动扫描 1.8 倍+ 高价
        ▸ 播报开关｜开关轮询自动播报
        ▸ 检测开关｜开关白名单群消息检测
        ▸ 查询统计 [<作物>]｜作物查询次数榜
        ▸ 状态｜当前群配置 + 数据看板图
        ▸ 帮助｜查看简版帮助
        ▸ 居所｜查看本指令总览

        ━━━━ 管理员 ━━━━
        ▸ 自定义回复 <内容>｜设置 / 清空群自动回复
        ▸ 设置 <作物> 阈值 <数字>｜设作物播报阈值
        ▸ 设置撤回 <秒数>｜结果自动撤回（0 关闭）
        ▸ 清除最高价 [<作物> | 全部]｜清历史最高价

        🔗 github.com/YDMY007/astrbot_plugin_jusuo
        """).strip()
        async for m in self._send_result(event, text):
            yield m

    @filter.command("状态")
    async def cmd_status(self, event: AstrMessageEvent):
        # 优先出图（所见即所得的「完整数据页面」）
        img = await self._generate_status_image()
        if img and await self._send_image_to_group(event, img, label="状态图"):
            return

        # 无 chromium / 非 QQ 群：降级为文字汇总
        poll_on = self.polling_enabled

        # ── 运行概览 ──
        total_map = self._crop_query_counts.get("total", {}) or {}
        total_q = sum(total_map.values())
        top_crop, top_n = "", 0
        if total_map:
            top_crop, top_n = max(total_map.items(), key=lambda kv: kv[1])
        录入 = sum(len(v) for v in self._录入_records.get("uids", {}).values())

        # ── 历史最高价（top3） ──
        highs = sorted(self._high_records.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)[:3]
        high_lines = [f"  💰 {c} {rec.get('income_str','?')}万 · 📦{rec.get('quantity',0)}" for c, rec in highs] or ["  （暂无）"]

        # ── 作物查询热度（top5） ──
        heat = sorted(total_map.items(), key=lambda kv: kv[1], reverse=True)[:5]
        heat_lines = [f"  🌾 {c} {n} 次" for c, n in heat] or ["  （暂无）"]

        # ── 播报阈值 ──
        threshold_lines = []
        for crop in KNOWN_CROPS:
            t = self._poll_thresholds.get(crop, DEFAULT_POLL_THRESHOLDS.get(crop, 9_990_000))
            icon = "📡" if crop in self.poll_crop_filter else "⏸️"
            threshold_lines.append(f"  {icon} {crop} ≥{t/10000:.0f}万")

        def _on(cond): return "✅" if cond else "❌"

        # ── 当前群配置 ──
        cur_gid = self._get_group_id(event)
        group_blocks = []
        if cur_gid and cur_gid in self.whitelist_groups:
            s = self._group_settings.get(cur_gid, {})
            has_own = any(k in s for k in (
                "crop_detect", "at_reply", "merchant_reply",
                "enable_source1", "enable_source2", "enable_source3",
                "custom_reply", "polling_enabled", "poll_crops",
            ))
            tag = "🔧独立" if has_own else "📋继承"
            group_blocks.append(f"▸ 当前群 {cur_gid} {tag}")

            def _sv(key, gv):
                v = s.get(key)
                return v if v is not None else gv

            group_blocks.append(
                f"  {_on(_sv('crop_detect', self.whitelist_crop_detect))}作物  "
                f"{_on(_sv('at_reply', self.whitelist_at_reply))}提及  "
                f"{_on(_sv('merchant_reply', self.whitelist_merchant_reply))}商人"
            )
            group_blocks.append(
                f"  {_on(_sv('enable_source1', self.enable_source1))}源一  "
                f"{_on(_sv('enable_source2', self.enable_source2))}源二  "
                f"{_on(_sv('enable_source3', self.enable_source3))}源三"
            )
            pp_val = _sv("polling_enabled", poll_on)
            cr_val = _sv("custom_reply", self.custom_reply)
            group_blocks.append(
                f"  {_on(pp_val)}播报  {_on(pp_val)}监控  "
                f"{_on(bool(cr_val))}回复"
            )

        # ── 组装 ──
        lines = [
            f"📊 王世杰居所助手 v1.12",
            f"轮询播报 {_on(poll_on)} · 每{self.poll_interval_minutes}分钟 · 监控{len(self.poll_crop_filter)}种",
            "",
            "━━ 运行概览 ━━",
            f"  🔎 累计查询 {total_q} 次",
            f"  🌾 查询最多：{top_crop or '暂无'}" + (f"（{top_n} 次）" if top_crop else ""),
            f"  🗂️ 已录入数据 {录入} 条",
            "",
            "━━ 历史最高价（Top3） ━━",
            *high_lines,
            "",
            "━━ 作物查询热度（Top5） ━━",
            *heat_lines,
            "",
            "━━ 播报阈值 ━━",
            *threshold_lines,
            "",
            "━━ 全局 ━━",
            f"  {_on(self.whitelist_crop_detect)}作物  "
            f"{_on(self.whitelist_at_reply)}提及  "
            f"{_on(self.whitelist_merchant_reply)}商人",
            f"  {_on(self.enable_source1)}源一  "
            f"{_on(self.enable_source2)}源二  "
            f"{_on(self.enable_source3)}源三",
            f"  {_on(bool(self.custom_reply))}自定义回复",
            f"  ⏱️ 撤回 {self.recall_seconds}s" if self.recall_seconds > 0 else "  ⏱️ 撤回 关闭",
            "",
            "━━ 启用列表 ━━",
            f"  ▸ {len(self.whitelist_groups)}个白名单群 · {len(self.admin_qqs)}个管理员",
        ]
        if group_blocks:
            lines.append("")
            lines.append("━━ 当前群配置 ━━")
            lines.extend(group_blocks)
        elif cur_gid:
            lines.append("")
            lines.append(f"━━ 当前群 {cur_gid} 不在白名单 ━━")

        text = chr(10).join(lines)
        async for m in self._send_result(event, text):
            yield m

    # ---- 管理员指令：自定义自动回复 ----

    @filter.command("自定义回复")
    async def cmd_custom_reply(self, event: AstrMessageEvent, text: str = ""):
        """管理员设置/清空自定义自动回复内容"""
        sender_qq = self._get_sender_qq(event)
        logger.info(f"[居所] 自定义回复指令 sender_qq='{sender_qq}' admin_qqs={self.admin_qqs} is_admin={self._is_admin(event)}")
        if not self._is_admin(event):
            yield event.plain_result(f"❌ 仅管理员可设置自定义回复，请在控制面板配置管理员QQ\n[调试] 你的QQ: {sender_qq}, 管理员列表: {self.admin_qqs}")
            return
        if text:
            self.custom_reply = text
            yield event.plain_result(f"✅ 自定义回复已设置（{len(text)}字）\n白名单群内@机器人将回复此内容")
        else:
            self.custom_reply = ""
            yield event.plain_result("✅ 已清空自定义回复，恢复默认使用指南")

    # 群消息监听：白名单群 @提及 / 关键词 自动回复
    # 使用 r".*" 匹配所有消息（AstrBot 中 r"." 可能只匹配单字符消息）
    _msg_handler_initialized: bool = False

    @filter.regex(r".*")
    async def _on_group_msg_check(self, event: AstrMessageEvent):
        """检测白名单群内的 @提及 和关键词，自动回复"""
        # 首次触发时 dump 消息对象属性，用于诊断
        if not JusuoPlugin._msg_handler_initialized:
            JusuoPlugin._msg_handler_initialized = True
            msg = event.message_obj
            attrs = {attr: str(getattr(msg, attr, None))[:100] for attr in dir(msg) if not attr.startswith("_") and not callable(getattr(msg, attr, None))}
            logger.info(f"[居所] 消息对象属性: {attrs}")
            logger.info(f"[居所] message_str='{event.message_str[:200] if event.message_str else ''}'")

        # 拦截机器人自身消息（含 Agent 生成的命令回显），防止自触发循环
        if self._is_self_message(event):
            logger.debug(f"[居所] 忽略机器人自身消息 sender={self._get_sender_qq(event)}")
            return

        # 拦截 Agent 直接执行的 Python 代码片段（astrbot_execute_python 回显），跳过匹配
        if self._is_agent_code_execution(event):
            logger.debug(f"[居所] 忽略 Agent 代码执行回显")
            return

        # 每次收到群消息时尝试缓存 adapter（供轮询广播使用）
        self._cache_adapter_from_event(event)

        gid = self._get_group_id(event)
        text = (event.message_str or "").strip()
        logger.debug(f"[居所] 收到消息 gid='{gid}' text='{text[:80]}' whitelist={self.whitelist_groups}")

        if not gid or gid not in self.whitelist_groups:
            if gid:
                logger.debug(f"[居所] 群{gid}不在白名单中")
            return

        # 获取该群的独立设置（未设置则用全局默认值）
        crop_detect = self._get_group_setting(gid, "crop_detect")
        if crop_detect is None:
            crop_detect = self.whitelist_crop_detect
        at_reply = self._get_group_setting(gid, "at_reply")
        if at_reply is None:
            at_reply = self.whitelist_at_reply
        merchant_reply = self._get_group_setting(gid, "merchant_reply")
        if merchant_reply is None:
            merchant_reply = self.whitelist_merchant_reply

        # 无任何检测需求时提前返回
        if not crop_detect and not at_reply and not merchant_reply:
            return

        is_at = self._check_at_bot(event)
        # 防误匹：仅当整条消息完全等于关键词时才触发（非子串匹配）
        matched_crop = next((kw for kw in KNOWN_CROPS if kw == text), None)
        matched_merchant = None
        matched_ranch = None
        matched_furniture = None
        # 商人名/牧场/家具名检测：先确保缓存已加载（首次会请求API，后续走10分钟缓存）
        if crop_detect and not matched_crop:
            # 商人名匹配（优先于牧场/家具，因为商人名仅2-3个字，更精确）
            matched_merchant = next((m for m in KNOWN_MERCHANTS if m == text), None)
            if not matched_merchant:
                await self._ensure_ranch_products()
                matched_ranch = next((pn for pn in self._ranch_product_names if pn == text), None)
                if not matched_ranch:
                    await self._ensure_furniture_names()
                    matched_furniture = next((fn for fn in self._furniture_names if fn == text), None)
        has_merchant_keyword = (text == "商人")
        logger.info(f"[居所] 白名单群{gid} is_at={is_at} crop='{matched_crop}' merchant='{matched_merchant}' ranch='{matched_ranch}' furniture='{matched_furniture}' text='{text[:100]}'")

        if matched_crop and crop_detect:
            # 检测到作物名 → 设置标志防止 command handler 重复触发
            event._jusuo_handled = True
            block_msg = self._check_qq_rate_limit(event)
            if block_msg:
                yield event.plain_result(block_msg)
                return
            logger.info(f"[居所] 检测到作物'{matched_crop}'，自动查询高倍信息")
            async for result in self._do_crop_query(event, matched_crop):
                yield result
        elif matched_merchant and crop_detect:
            # 检测到商人名 → 自动查询收购分享
            event._jusuo_handled = True
            block_msg = self._check_qq_rate_limit(event)
            if block_msg:
                yield event.plain_result(block_msg)
                return
            logger.info(f"[居所] 检测到商人'{matched_merchant}'，自动查询")
            yield event.plain_result(f"🏪 正在查询商人「{matched_merchant}」的分享...")
            # 商人查询尊重群独立数据源开关
            es1 = self._get_group_setting(gid, "enable_source1")
            if es1 is None:
                es1 = self.enable_source1
            if not es1:
                yield event.plain_result("❌ 当前群已禁用数据源1，无法查询商人收购分享")
                return
            data = await self._fetch_source1_all("purchase", merchant=matched_merchant)
            if data is None:
                yield event.plain_result("❌ 查询失败")
                return
            if not data:
                yield event.plain_result(f"📭 未找到商人「{matched_merchant}」的分享")
                return
            text = self._format_crop_result(f"商人:{matched_merchant}", data)
            async for m in self._send_result(event, text, recall_after=self.recall_seconds):
                yield m
        elif matched_ranch and crop_detect:
            # 检测到牧场产品名 → 自动查询牧场分享
            event._jusuo_handled = True
            block_msg = self._check_qq_rate_limit(event)
            if block_msg:
                yield event.plain_result(block_msg)
                return
            logger.info(f"[居所] 检测到牧场产品'{matched_ranch}'，自动查询")
            result = await self._query_ranch(matched_ranch, gid)
            async for m in self._send_result(event, result, recall_after=self.recall_seconds):
                yield m
        elif matched_furniture and crop_detect:
            # 检测到家具名 → 自动查询家具分享
            event._jusuo_handled = True
            block_msg = self._check_qq_rate_limit(event)
            if block_msg:
                yield event.plain_result(block_msg)
                return
            logger.info(f"[居所] 检测到家具'{matched_furniture}'，自动查询")
            result = await self._query_furniture(matched_furniture, gid)
            async for m in self._send_result(event, result, recall_after=self.recall_seconds):
                yield m
        elif (is_at and at_reply) or (has_merchant_keyword and merchant_reply):
            # @提及 / "商人"关键词（不含具体名字）→ 自动回复使用指南或自定义内容
            reply = self._whitelist_auto_reply(gid)
            logger.info(f"[居所] 触发自动回复，内容类型={'自定义' if self.custom_reply else '默认'}")
            yield event.plain_result(reply)

    # ---- 轮询播报控制 ----

    @filter.command("刷二")
    async def cmd_poll_now(self, event: AstrMessageEvent):
        """手动触发一次高价播报（无视缓存，显示全部）"""
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        yield event.plain_result("🔍 正在扫描高价作物...")
        msg = await self._do_poll_2x(force=True)
        if msg:
            async for m in self._send_result(event, msg, recall_after=self.recall_seconds):
                yield m
        else:
            yield event.plain_result("📭 当前没有达到播报阈值的收购分享")

    @filter.command("播报开关")
    async def cmd_poll_toggle(self, event: AstrMessageEvent):
        self.polling_enabled = not self.polling_enabled
        status = "已开启" if self.polling_enabled else "已关闭"
        yield event.plain_result(f"🔔 高价自动播报 {status}（每{self.poll_interval_minutes}分钟，监控 {len(self.poll_crop_filter)} 种作物）")

    @filter.command("设置")
    async def cmd_set_threshold(self, event: AstrMessageEvent, crop: str = "", threshold_val: str = ""):
        """管理员设置某个作物的播报阈值：设置 <作物名> 播报阈值 <数值>"""
        if not self._is_admin(event):
            yield event.plain_result("❌ 仅管理员可设置播报阈值")
            return
        if not crop:
            yield event.plain_result("❌ 格式：设置 <作物名> 播报阈值 <数值>\n如：设置 辣椒 播报阈值 5000000")
            return

        # 解析：尝试从参数中提取作物名和数值
        # AstrBot 会把剩余部分按空格分给 crop 和 threshold_val
        # 如 "设置 辣椒 5000000" → crop="辣椒", threshold_val="5000000"
        # 如 "设置 辣椒 播报阈值 5000000" → 可能 crop="辣椒", threshold_val="播报阈值"
        val_str = threshold_val

        # 如果 val_str 包含 "播报阈值" 或 "阈值"，提取后面的数字
        for kw in ("播报阈值", "阈值"):
            if kw in val_str:
                val_str = val_str.replace(kw, "").strip()
                break

        # 降级：若仍未提取到纯数字，从原始消息中提取最后一个数字片段
        if not val_str.isdigit():
            raw_parts = (event.message_str or "").strip().split()
            for part in reversed(raw_parts):
                part = part.replace(",", "").replace("万", "0000").replace("w", "0000").replace("W", "0000")
                if part.lstrip('-').isdigit():
                    val_str = part
                    break

        # 匹配作物名（精确优先，模糊降级）
        matched_crop = next((c for c in KNOWN_CROPS if c == crop), None)
        if not matched_crop:
            matched_crop = next((c for c in KNOWN_CROPS if crop in c), None)
        if not matched_crop:
            yield event.plain_result(f"❌ 未识别作物「{crop}」\n可用作物：{'、'.join(KNOWN_CROPS)}")
            return

        try:
            val = int(val_str)
        except (ValueError, TypeError):
            yield event.plain_result(f"❌ 阈值「{val_str}」不是有效数字\n格式：设置 {matched_crop} 播报阈值 5000000")
            return
        if val < 0:
            yield event.plain_result("❌ 阈值不能为负数")
            return

        self._poll_thresholds[matched_crop] = val
        # 同步回写到 AstrBot 配置，使 WebUI 显示最新值
        if self.config:
            config_key = f"poll_threshold_{matched_crop}"
            self.config[config_key] = val
            try:
                self.config.save_config()
            except Exception as e:
                logger.warning(f"[居所] 保存阈值配置到 WebUI 失败: {e}")
        wan = val / 10000
        yield event.plain_result(f"✅ 「{matched_crop}」播报阈值已设为 {wan:.0f}万百工币\n（收益≥此值的收购才会播报）")

    @filter.command("设置撤回")
    async def cmd_set_recall(self, event: AstrMessageEvent, seconds: str = ""):
        """管理员设置查询结果自动撤回秒数：设置撤回 <秒数>（0=关闭）"""
        if not self._is_admin(event):
            yield event.plain_result("❌ 仅管理员可设置撤回时间")
            return
        if not seconds:
            cur = self.recall_seconds
            tip = f"当前撤回时间：{cur}秒" if cur > 0 else "当前：不撤回"
            yield event.plain_result(f"⏱️ {tip}\n格式：设置撤回 <秒数>（0=关闭撤回，如：设置撤回 60）")
            return
        try:
            val = int(seconds.replace("秒", "").strip())
        except (ValueError, TypeError):
            yield event.plain_result(f"❌ 「{seconds}」不是有效数字\n格式：设置撤回 <秒数>（0=关闭）")
            return
        if val < 0:
            yield event.plain_result("❌ 撤回秒数不能为负数")
            return
        self.recall_seconds = val
        # 同步回写到 AstrBot 配置，使 WebUI 显示最新值
        if self.config:
            self.config["recall_seconds"] = val
            try:
                self.config.save_config()
            except Exception as e:
                logger.warning(f"[居所] 保存撤回配置到 WebUI 失败: {e}")
        tip = f"✅ 查询结果将在 {val} 秒后自动撤回" if val > 0 else "✅ 已关闭查询结果自动撤回"
        yield event.plain_result(tip)

    @filter.command("清除最高价")
    async def cmd_clear_high(self, event: AstrMessageEvent, crop: str = ""):
        """管理员清除指定作物的历史最高价记录（用于清理捣乱/误录入的虚假高价数据）"""
        if not self._is_admin(event):
            yield event.plain_result("❌ 仅管理员可清除历史最高价记录")
            return

        # 解析作物名：取整条消息去掉指令词后的剩余部分（最稳健，不依赖参数切分）
        raw = (event.message_str or "").strip()
        q = ""
        for kw in ("清除最高价", "清除高价", "清除最高"):
            if raw.startswith(kw):
                q = raw[len(kw):].strip()
                break
        if not q:
            q = (crop or "").strip()

        if not q:
            avail = "、".join(self._high_records.keys()) or "（暂无记录）"
            yield event.plain_result(
                "❌ 格式：清除最高价 <作物名>\n"
                "示例：清除最高价 蝶影莲子\n"
                "当前已记录作物：" + avail
            )
            return

        # 清空全部（管理员显式输入「全部/所有/all」才触发）
        if q in ("全部", "所有", "all", "ALL"):
            n = len(self._high_records)
            if n == 0:
                yield event.plain_result("ℹ️ 当前没有任何历史最高价记录可清除")
                return
            self._high_records.clear()
            self._save_high_records()
            logger.info(f"[居所] 管理员清空全部历史最高价记录（{n} 种）")
            yield event.plain_result(f"🧹 已清空全部 {n} 种作物的历史最高价记录")
            return

        # 构造候选名（含去掉常见后缀的变体），精确优先、模糊降级
        candidates = [q]
        for suf in ("的最高价", "最高价", "的记录", "记录", "数据", "价格", "的"):
            if q.endswith(suf):
                candidates.append(q[: -len(suf)].strip())

        key = None
        for cand in candidates:
            if not cand:
                continue
            if cand in self._high_records:
                key = cand
                break
            norm = next((c for c in KNOWN_CROPS if c == cand), None)
            if norm and norm in self._high_records:
                key = norm
                break
        if key is None:
            # 模糊：候选中任意一段作为子串命中记录 key
            hits = [k for k in self._high_records if any(c and c in k for c in candidates)]
            if len(hits) == 1:
                key = hits[0]
            elif len(hits) > 1:
                yield event.plain_result(
                    f"❌ 「{q}」匹配到多个作物，请写完整名称：\n" + "、".join(hits)
                )
                return

        if not key:
            avail = "、".join(self._high_records.keys()) or "（暂无记录）"
            yield event.plain_result(
                f"❌ 未找到作物「{q}」的历史最高价记录\n当前已记录作物：{avail}"
            )
            return

        old = self._high_records[key]
        old_inc = old.get("income_str", "?")
        old_qty = old.get("quantity", 0)
        self._high_records.pop(key)
        self._save_high_records()
        logger.info(f"[居所] 管理员清除历史最高价：{key}（原 💰{old_inc}万 量{old_qty}）")
        yield event.plain_result(
            f"🧹 已清除「{key}」的历史最高价记录\n"
            f"（原最高 💰{old_inc}万 · 量 {old_qty}）\n"
            "后续轮询到更高价时会自动重新记录"
        )

    @filter.command("检测开关")
    async def cmd_detection_toggle(self, event: AstrMessageEvent):
        """开关白名单群消息内容检测（全部三项）"""
        new_state = not (self.whitelist_crop_detect and self.whitelist_at_reply and self.whitelist_merchant_reply)
        self.whitelist_crop_detect = new_state
        self.whitelist_at_reply = new_state
        self.whitelist_merchant_reply = new_state
        status = "已开启" if new_state else "已关闭"
        yield event.plain_result(f"🔍 白名单群消息检测 {status}\n（作物名自动查询 / @提及回复 / 商人关键词回复）")

    @filter.command("商人")
    async def cmd_merchant(self, event: AstrMessageEvent):
        """直接发"商人"显示已知商人列表"""
        merchants = "、".join(KNOWN_MERCHANTS)
        yield event.plain_result(
            f"🏪 已知商人：{merchants}\n\n"
            f"💡 发送「搜索 <商人名>」查询该商人的收购分享"
        )

    # ---- 商人查询 ----

    # ---- 作物查询 ----

    @filter.command("高倍")
    async def cmd_gaobei(self, event: AstrMessageEvent, name: str = ""):
        if getattr(event, "_jusuo_handled", False):
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        if not name:
            yield event.plain_result("❌ 请输入作物名，如：高倍 旭日辣椒")
            return
        if name not in KNOWN_CROPS:
            yield event.plain_result(
                f"❌ 「{name}」不是已知作物\n"
                f"💡 可用作物：\n\n" + "\n\n".join(f"  · {c}" for c in KNOWN_CROPS)
            )
            return
        async for result in self._do_crop_query(event, name):
            yield result

    # ---- 直接发作物名也触发查询（每个作物独立注册，避免堆叠装饰器问题） ----

    @filter.command("炎霞辣椒")
    async def _crop_yanxia(self, event: AstrMessageEvent):
        if getattr(event, "_jusuo_handled", False):
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        async for result in self._do_crop_query(event, "炎霞辣椒"):
            yield result

    @filter.command("灿金云棉")
    async def _crop_canjin(self, event: AstrMessageEvent):
        if getattr(event, "_jusuo_handled", False):
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        async for result in self._do_crop_query(event, "灿金云棉"):
            yield result

    @filter.command("曳紫云棉")
    async def _crop_yezi(self, event: AstrMessageEvent):
        if getattr(event, "_jusuo_handled", False):
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        async for result in self._do_crop_query(event, "曳紫云棉"):
            yield result

    @filter.command("旭日辣椒")
    async def _crop_xuri(self, event: AstrMessageEvent):
        if getattr(event, "_jusuo_handled", False):
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        async for result in self._do_crop_query(event, "旭日辣椒"):
            yield result

    @filter.command("胭纱云棉")
    async def _crop_yansha(self, event: AstrMessageEvent):
        if getattr(event, "_jusuo_handled", False):
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        async for result in self._do_crop_query(event, "胭纱云棉"):
            yield result

    @filter.command("星夜龙眼")
    async def _crop_xingye(self, event: AstrMessageEvent):
        if getattr(event, "_jusuo_handled", False):
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        async for result in self._do_crop_query(event, "星夜龙眼"):
            yield result

    @filter.command("蝶影莲子")
    async def _crop_dieying(self, event: AstrMessageEvent):
        if getattr(event, "_jusuo_handled", False):
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        async for result in self._do_crop_query(event, "蝶影莲子"):
            yield result

    # ---- 牧场查询 ----

    @filter.command("牧场")
    async def cmd_ranch(self, event: AstrMessageEvent, name: str = ""):
        if getattr(event, "_jusuo_handled", False):
            return
        if not name:
            yield event.plain_result("❌ 请输入产品名，如：牧场 云不见蛋")
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        yield event.plain_result(f"🐄 正在查询「{name}」牧场产品...")
        result = await self._query_ranch(name, self._get_group_id(event))
        async for m in self._send_result(event, result, recall_after=self.recall_seconds):
            yield m

    # ---- 家具查询 ----

    @filter.command("家具")
    async def cmd_furniture(self, event: AstrMessageEvent, name: str = ""):
        if getattr(event, "_jusuo_handled", False):
            return
        if not name:
            yield event.plain_result("🪑 正在生成家具图鉴...")
            img_path = await self._generate_furniture_image()
            if img_path:
                sent = await self._send_image_to_group(event, img_path, label="家具图鉴")
                if sent:
                    return
            # Playwright 不可用或发送失败 → 回退文字列表
            lines = ["🪑 可查家具列表"]
            for merchant in KNOWN_MERCHANTS:
                mf_map = MERCHANT_FURNITURE_MAP.get(merchant, {})
                all_names = [n for names in mf_map.values() for n in names]
                lines.append(f"\n🏷️ {merchant}（{len(all_names)}件）：{', '.join(all_names[:8])}{'...' if len(all_names) > 8 else ''}")
            lines.append(f"\n💡 发送「家具 <名称>」查询 / 发送「搜索 <商人名>」查商人列表")
            yield event.plain_result("\n".join(lines))
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        yield event.plain_result(f"🪑 正在查询「{name}」家具分享...")
        result = await self._query_furniture(name, self._get_group_id(event))
        async for m in self._send_result(event, result, recall_after=self.recall_seconds):
            yield m

    # ---- 交友墙 ----

    @filter.command("交友墙")
    async def cmd_wall(self, event: AstrMessageEvent):
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        yield event.plain_result("💬 正在获取搭子交友墙...")
        data = await self._fetch_supabase(TABLE_PARTNER, order="created_at.desc", limit=5)
        if data is None:
            yield event.plain_result("❌ 查询失败")
            return
        if not data:
            yield event.plain_result("📭 暂无搭子信息")
            return
        recall_hint = f" · {self.recall_seconds}s撤回" if self.recall_seconds > 0 else ""
        lines = [f"💬 搭子交友墙{recall_hint}\n\n共{len(data)}条 | 最新优先"]
        for i, item in enumerate(data):
            uid = str(item.get("uid", "?"))[:12]
            gname = item.get("game_name", "?")
            ptype = item.get("type", "?")
            lines.append(f"  {i+1}. {gname} · {ptype}\n\n     UID {uid}")
        async for m in self._send_result(event, "\n\n".join(lines), recall_after=self.recall_seconds):
            yield m

    # ---- 模板 ----

    @filter.command("模板")
    async def cmd_template(self, event: AstrMessageEvent):
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        yield event.plain_result("🏗️ 正在获取热门模板...")
        data = await self._fetch_supabase(TABLE_TEMPLATE, order="heat_score.desc", limit=5)
        if data is None:
            yield event.plain_result("❌ 查询失败")
            return
        if not data:
            yield event.plain_result("📭 暂无模板")
            return
        recall_hint = f" · {self.recall_seconds}s撤回" if self.recall_seconds > 0 else ""
        lines = [f"🏗️ 热门建造模板{recall_hint}\n\nTOP {len(data)} | 按热度↓"]
        for i, item in enumerate(data):
            title = item.get("title", "?")
            heat = item.get("heat_score", 0)
            likes = item.get("like_count", 0)
            region = item.get("region", "?")
            lines.append(f"  {i+1}. {title}\n\n     🔥{heat}  ❤️{likes}  📍{region}")
        async for m in self._send_result(event, "\n\n".join(lines), recall_after=self.recall_seconds):
            yield m

    # ---- 智能搜索 ----

    @filter.command("搜索")
    async def cmd_search(self, event: AstrMessageEvent, keyword: str = ""):
        if getattr(event, "_jusuo_handled", False):
            return
        if not keyword:
            yield event.plain_result("❌ 请输入关键词，如：搜索 辣椒")
            return
        block_msg = self._check_qq_rate_limit(event)
        if block_msg:
            yield event.plain_result(block_msg)
            return
        matched = None
        for crop in KNOWN_CROPS:
            if keyword in crop or crop in keyword:
                matched = crop
                break
        if matched:
            async for result in self._do_crop_query(event, matched):
                yield result
            return
        for merchant in KNOWN_MERCHANTS:
            if keyword in merchant or merchant in keyword:
                matched = merchant
                break
        if matched:
            yield event.plain_result(f"🏪 正在查询商人「{matched}」的分享...")
            search_gid = self._get_group_id(event)
            es1 = self._get_group_setting(search_gid, "enable_source1")
            if es1 is None:
                es1 = self.enable_source1
            if not es1:
                yield event.plain_result("❌ 当前群已禁用数据源1，无法查询商人收购分享")
                return
            data = await self._fetch_source1_all("purchase", merchant=matched)
            if data is None:
                yield event.plain_result("❌ 查询失败")
                return
            if not data:
                yield event.plain_result(f"📭 未找到商人「{matched}」的分享")
                return
            # _format_crop_result 内部会按百工币重新排序
            text = self._format_crop_result(f"商人:{matched}", data)
            async for m in self._send_result(event, text, recall_after=self.recall_seconds):
                yield m
            return
        yield event.plain_result("🔍 正在搜索...")
        async for result in self._do_crop_query(event, keyword):
            yield result

    # ---- 查询统计 ----

    @filter.command("查询统计")
    async def cmd_crop_query_stats(self, event: AstrMessageEvent, arg: str = ""):
        """查看作物被查询的次数：全榜 / 指定作物"""
        counts = self._crop_query_counts.get("total", {}) or {}
        if not counts:
            yield event.plain_result(
                f"📊 暂无查询次数统计\n（自 {self.version_date} 起开始计数）"
            )
            return
        arg = arg.strip()
        if arg:
            n = int(counts.get(arg, 0))
            if n <= 0:
                yield event.plain_result(f"📊 「{arg}」暂无查询记录")
            else:
                yield event.plain_result(f"📊 「{arg}」被查询 {n} 次（自 {self.version_date} 起）")
            return
        # 全榜：按次数降序
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        lines = [f"📊 作物查询次数统计（自 {self.version_date} 起）", ""]
        for i, (crop, n) in enumerate(ranked, 1):
            lines.append(f"  {i}. 🌾 {crop}  ·  {n} 次")
        lines.append("")
        total = sum(counts.values())
        lines.append(f"共 {len(ranked)} 种作物 · 累计 {total} 次查询")
        async for m in self._send_result(event, "\n".join(lines), recall_after=0):
            yield m

    # ==================== 核心查询：多源合并 ====================

    def _resolve_crop_name(self, name: str) -> str:
        """将用户输入解析为规范作物名（与 KNOWN_CROPS / 轮询 key 对齐），避免混作物与历史最高错配"""
        if not name:
            return name
        if name in KNOWN_CROPS:
            return name
        cands = [c for c in KNOWN_CROPS if name in c or c in name]
        if cands:
            cands.sort(key=lambda c: len(c))
            return cands[0]
        return name

    async def _do_crop_query(self, event: AstrMessageEvent, name: str):
        """从多个数据源查询作物"""
        self._increment_crop_count(name)
        yield event.plain_result(f"🌿 正在查询「{name}」收购信息")

        # 解析为规范作物名，与轮询 key 对齐，避免历史最高错配 / 混作物
        name = self._resolve_crop_name(name)

        # 确保单价缓存
        await self._ensure_unit_prices()
        unit_price = self._get_unit_price(name)

        # 数据源开关：群独立 > 全局
        gid = self._get_group_id(event)
        es1 = self._get_group_setting(gid, "enable_source1")
        if es1 is None:
            es1 = self.enable_source1
        es2 = self._get_group_setting(gid, "enable_source2")
        if es2 is None:
            es2 = self.enable_source2
        es3 = self._get_group_setting(gid, "enable_source3")
        if es3 is None:
            es3 = self.enable_source3

        tasks = []
        if es1:
            tasks.append(("source1", self._fetch_source1_all("purchase")))
        if es2:
            tasks.append(("source2", self._fetch_hok_items(name)))
        if es3:
            tasks.append(("source3", self._fetch_wsjj_items(name)))

        # 并发请求
        raw_results = {}
        for tag, coro in tasks:
            try:
                raw_results[tag] = await coro
            except Exception as e:
                logger.warning(f"{tag} 查询异常: {e}")
                raw_results[tag] = None

        # 归一化合并
        all_items = []
        seen_uids = set()

        # 源1：public-query 返回全量数据，按 crop_name 精确过滤
        source1_data = raw_results.get("source1") or []
        for item in source1_data:
            if item.get("crop_name") != name:
                continue
            uid = str(item.get("uid", ""))
            if uid and uid not in seen_uids:
                seen_uids.add(uid)
                all_items.append({
                    "uid": uid,
                    "crop_name": item.get("crop_name", name),
                    "price_multiplier": float(item.get("price_multiplier") or 0),
                    "quantity": int(item.get("quantity") or 0),
                    "merchant": item.get("merchant_name", "?"),
                    "source": SOURCE1_NAME,
                    "unit_price": unit_price,
                    "stall_level": int(item.get("residence_level") or 1),
                    "guild_maxed": bool(item.get("guild_maxed") or False),
                    "sale_price": int(item.get("sale_price") or 0),
                })

        if raw_results.get("source2"):
            for item in raw_results["source2"]:
                if item.get("capped"):
                    continue
                if item.get("crop_name") != name:
                    continue
                uid = str(item.get("uid", ""))
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    all_items.append({
                        "uid": uid,
                        "crop_name": item.get("crop_name", name),
                        "price_multiplier": float(item.get("price_multiplier") or 0),
                        "quantity": int(item.get("quantity") or 0),
                        "merchant": item.get("merchant", "?"),
                        "source": SOURCE2_NAME,
                        "unit_price": unit_price,
                        "stall_level": int(item.get("home_level") or 1),
                        "guild_maxed": item.get("home_max_level", "") == "是",
                        # 源2 自带精确售价 expected_income，直接采用，避免依赖 unit_prices 查表（查不到时为0）
                        "sale_price": int(float(item.get("expected_income") or 0)),
                    })

        # 源3：家园站 — sold_out 或 markUsers非空 视为已达上限剔除
        if raw_results.get("source3"):
            for item in raw_results["source3"]:
                if item.get("status") == "sold_out":
                    continue
                if item.get("markUsers"):  # 至少一人标记=已达上限
                    continue
                if item.get("cropName") != name:
                    continue
                uid = str(item.get("uid", ""))
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    all_items.append({
                        "uid": uid,
                        "crop_name": item.get("cropName", name),
                        "price_multiplier": float(item.get("multiplier") or 0),
                        "quantity": int(item.get("quantity") or 0),
                        "merchant": item.get("merchantName", "?"),
                        "source": SOURCE3_NAME,
                        "unit_price": float(item.get("unitPrice") or unit_price),
                        "stall_level": int(item.get("stallLevel") or 1),
                        "guild_maxed": item.get("baijiaMax") is True,
                    })

        # 模糊匹配 fallback（仅源1精确匹配无结果时）—— 仅接受与规范名完全一致的单一作物，杜绝混作物
        if not all_items and source1_data:
            for item in source1_data:
                cn = (item.get("crop_name") or "").strip()
                if not cn or cn != name.strip():
                    continue
                uid = str(item.get("uid", ""))
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    all_items.append({
                        "uid": uid,
                        "crop_name": cn,
                        "price_multiplier": float(item.get("price_multiplier") or 0),
                        "quantity": int(item.get("quantity") or 0),
                        "merchant": item.get("merchant_name", "?"),
                        "source": SOURCE1_NAME,
                        "unit_price": unit_price,
                        "stall_level": int(item.get("residence_level") or 1),
                        "guild_maxed": bool(item.get("guild_maxed") or False),
                        "sale_price": int(item.get("sale_price") or 0),
                    })

        if not all_items:
            similar = [c for c in KNOWN_CROPS if name in c or c in name]
            hint = "\n\n".join(f"  · {c}" for c in (similar or KNOWN_CROPS))
            yield event.plain_result(
                f"📭 未找到「{name}」的收购分享\n\n"
                f"💡 可用作物：\n\n{hint}"
            )
            return

        text = self._format_crop_result(name, all_items)
        async for m in self._send_result(event, text, recall_after=self.recall_seconds):
            yield m

    # ==================== 插件页面 Web API（pages/dashboard） ====================

    def _register_page_apis(self, context):
        """注册插件页面所需后端 API（前端 pages/dashboard 通过 bridge 调用）

        AstrBot 的插件页面路由匹配规则（已核对 dashboard/api/plugins.py 源码）：
        前端 bridge 把 apiGet("page/overview") 经 postMessage 交给 Dashboard，
        Dashboard 构造请求路径 /plugins/extensions/<plugin_path>，
        后端取 request_path = "/" + plugin_path，再用各插件 register_web_api 时的
        route 字符串做 re.fullmatch 精确匹配；框架【不会】自动加插件名前缀，
        plugin_path 整体就是 route 要匹配的内容。

        因此 route 必须自带真实 plugin_id 前缀。AstrBot 的 plugin_id 为
        "author/name"（本插件即 "亭子ww/jusuo"），但不同安装方式/版本下
        plugin_id 可能是目录名(astrbot_plugin_jusuo)或仅 name(jusuo)。
        为兼容各种约定，这里用运行时真实 self.plugin_id 动态拼前缀，
        并同时注册多种候选前缀，必然有一个与 Dashboard 请求精确匹配。
        """
        # 运行时真实 plugin_id（AstrBot 注入到 Star 实例）
        real_pid = getattr(self, "plugin_id", "") or "astrbot_plugin_jusuo"
        author, name_only = "亭子ww", "jusuo"
        # 候选前缀：空 / 真实id / 目录名 / 仅name / author/name
        prefixes = ["", real_pid, "astrbot_plugin_jusuo", name_only, f"{author}/{name_only}"]
        routes = [
            ("/page/overview", self.page_overview, ["GET"], "插件页概览统计"),
            ("/page/crop-heat", self.page_crop_heat, ["GET"], "作物查询次数热度"),
            ("/page/high-records", self.page_high_records, ["GET"], "历史最高价记录"),
        ]
        seen = set()
        for ep, handler, methods, desc in routes:
            for pref in prefixes:
                full = (f"/{pref}{ep}") if pref else ep
                if full in seen:
                    continue
                seen.add(full)
                context.register_web_api(full, handler, methods, desc)

    async def page_overview(self):
        """概览统计：累计查询次数 / 查询最多作物 / 已录入数据 / 配置状态"""
        # 「已录入数据」懒触发：距上次计算超过 30 分钟则在后台重算（不阻塞返回）
        try:
            import asyncio as _asyncio, time as _t
            if _t.time() - float(self._录入_records.get("last_compute", 0) or 0) > 1800:
                _asyncio.ensure_future(self._compute_录入_data())
        except Exception:
            pass
        total_map = self._crop_query_counts.get("total", {}) or {}
        total_queries = sum(total_map.values())
        crop_kinds = len(total_map)
        monitored = len(self.poll_crop_filter & set(KNOWN_CROPS))
        high_count = len(self._high_records)
        top_crop, top_count = "", 0
        if total_map:
            top_crop, top_count = max(total_map.items(), key=lambda kv: kv[1])
        # 各作物播报阈值（百工币，缺失用默认）
        thresholds = {}
        for _c in KNOWN_CROPS:
            thresholds[_c] = int(self._poll_thresholds.get(_c, DEFAULT_POLL_THRESHOLDS.get(_c, 9_990_000)))
        return json_response({
            "plugin": "王世杰居所助手",
            "version": "1.12",
            "data_since": getattr(self, "version_date", "2026-07-12"),
            "author": "亭子ww",
            "stats": {
                "total_queries": total_queries,
                "crop_kinds": crop_kinds,
                "monitored": monitored,
                "high_records": high_count,
                "录入_data": sum(len(v) for v in self._录入_records.get("uids", {}).values()),
                "top_crop": top_crop,
                "top_count": top_count,
                "polling_on": bool(getattr(self, "polling_enabled", False)),
            },
            "sources": {
                "source1": bool(getattr(self, "enable_source1", True)),
                "source2": bool(getattr(self, "enable_source2", True)),
                "source3": bool(getattr(self, "enable_source3", True)),
            },
            "recall_seconds": int(getattr(self, "recall_seconds", 0)),
            "config": {
                "poll_interval_minutes": int(getattr(self, "poll_interval_minutes", 3)),
                "monitored_crops": len(getattr(self, "poll_crop_filter", set()) or set()),
                "custom_reply_on": bool(getattr(self, "custom_reply", "")),
                "rate_limit_window": int(getattr(self, "_qq_rate_limit_window", 600)),
                "rate_limit_max": int(getattr(self, "_qq_rate_limit_max", 3)),
                "configured_groups": len(getattr(self, "_group_settings", {}) or {}),
                "whitelist_on": bool(getattr(self, "whitelist_groups", set())),
                "whitelist_crop_detect": bool(getattr(self, "whitelist_crop_detect", True)),
                "whitelist_at_reply": bool(getattr(self, "whitelist_at_reply", True)),
                "whitelist_merchant_reply": bool(getattr(self, "whitelist_merchant_reply", True)),
            },
            "thresholds": thresholds,
        })

    async def page_crop_heat(self):
        """作物查询次数热度：一次返回 日/周/总 三个区间的排名，前端本地切换无需重复请求（避免桥接代理丢失查询串）"""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        iso = now.isocalendar()
        cur_week = f"{iso[0]}-W{iso[1]:02d}"

        def _rank(pool):
            return sorted((pool or {}).items(), key=lambda kv: kv[1], reverse=True)

        total_map = self._crop_query_counts.get("total", {}) or {}
        daily_map = (self._crop_query_counts.get("daily", {}) or {}).get(today, {}) or {}
        weekly_map = (self._crop_query_counts.get("weekly", {}) or {}).get(cur_week, {}) or {}
        return json_response({
            "daily": [{"crop": c, "count": n} for c, n in _rank(daily_map)],
            "weekly": [{"crop": c, "count": n} for c, n in _rank(weekly_map)],
            "total": [{"crop": c, "count": n} for c, n in _rank(total_map)],
            "total_count": sum(total_map.values()),
        })

    async def page_high_records(self):
        """历史最高价记录列表"""
        recs = []
        for crop, rec in self._high_records.items():
            recs.append({
                "crop": crop,
                "quantity": rec.get("quantity", 0),
                "income": rec.get("income_str", "?"),
                "ts": rec.get("ts", 0),
            })
        recs.sort(key=lambda r: r.get("ts", 0), reverse=True)
        return json_response({"items": recs, "total": len(recs)})

    # ==================== Supabase 数据源 ====================

    async def _fetch_supabase(
        self,
        table: str,
        field: str = "",
        value: str = "",
        exact: bool = True,
        order: str = "",
        limit: int = 50,
    ) -> Optional[list]:
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://jusuo.playmmo.cn/",
            "Accept": "application/json",
        }
        if self.source1_api_key:
            headers["x-api-key"] = self.source1_api_key
        query_parts = [f"limit={limit}"]
        if order:
            query_parts.append(f"order={order}")
        if field and value:
            op = "eq" if exact else "ilike"
            val = value if exact else f"*{value}*"
            query_parts.append(f"{field}={op}.{val}")
        full_url = f"{self.supabase_url}/rest/v1/{table}?{'&'.join(query_parts)}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(full_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    # 401 时回退到内置默认 anon key 重试一次（配置里误填了错误 key 的情况）
                    if resp.status == 401 and self.anon_key != DEFAULT_ANON_KEY:
                        headers2 = dict(headers)
                        headers2["apikey"] = DEFAULT_ANON_KEY
                        headers2["Authorization"] = f"Bearer {DEFAULT_ANON_KEY}"
                        async with session.get(full_url, headers=headers2, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                            if resp2.status == 200:
                                logger.info("[居所] Supabase anon key 无效，已自动回退内置默认密钥")
                                return await resp2.json()
                            logger.warning(f"Supabase {table} [{resp2.status}]: {(await resp2.text())[:200]}")
                            return None
                    logger.warning(f"Supabase {table} [{resp.status}]: {(await resp.text())[:200]}")
                    return None
            except Exception as e:
                logger.error(f"Supabase 请求失败: {e}")
                return None

    # ==================== 网站一 public-query API（主数据源） ====================

    @staticmethod
    def _safe_int(val, default=0):
        """安全转为 int，处理 '未填写'/空/None/非数字字符串"""
        if val is None:
            return default
        if isinstance(val, (int, float)):
            return int(val)
        try:
            return int(float(str(val).strip()))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_mult(val) -> float:
        """解析收购倍率：'2倍'→2.0, '2.0'→2.0, 2→2.0"""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().rstrip("倍").rstrip("x").rstrip("X")
        try:
            return float(s)
        except ValueError:
            return 0.0

    @staticmethod
    def _normalize_source1_item(item: dict, data_type: str) -> dict:
        """将 public-query 中文响应字段转为规范化的英文字段"""
        result = {
            "uid": str(item.get("UID", "")),
            "merchant_name": str(item.get("商人名称", "")),
            "quantity": JusuoPlugin._safe_int(item.get("数量"), 0),
            "price_multiplier": JusuoPlugin._parse_mult(item.get("收购倍率", 0)),
            "sale_price": JusuoPlugin._safe_int(item.get("预计售价"), 0),
        }
        if data_type == "purchase":
            result["crop_name"] = str(item.get("作物名称", ""))
            result["residence_level"] = JusuoPlugin._safe_int(item.get("摊位等级"), 1)
            result["guild_maxed"] = item.get("百家满级") in (True, "是", "true", "True", 1)
        elif data_type == "ranch":
            result["product_name"] = str(item.get("产品名称", ""))
            result["guild_maxed"] = item.get("百家满级") in (True, "是", "true", "True", 1)
            result["residence_level"] = 1
        elif data_type == "furniture":
            flist = item.get("在售家具列表", [])
            if isinstance(flist, str):
                flist = [f.strip() for f in flist.replace("，", ",").split(",") if f.strip()]
            result["furniture_ids"] = flist
            result["like_count"] = JusuoPlugin._safe_int(item.get("点赞数"), 0)
        return result

    def _build_source1_headers(self) -> dict:
        """构建 public-query 请求头（x-api-key + 浏览器UA + Referer 防反爬）"""
        headers = {
            "x-api-key": self.source1_api_key or "",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://jusuo.playmmo.cn/",
        }
        return headers

    def _extract_items_from_response(self, data, data_type: str) -> tuple[list, Optional[int]]:
        """从 public-query 响应中提取 items 列表和 total 值
        返回 (items_list, total_or_None)

        新 public-query 格式：{类型, 分页:{总条数, 是否有下一页}, 条目列表:[...]}
        """
        total = None

        def _find_list(obj, depth=0):
            nonlocal total
            if depth > 2 or obj is None:
                return None
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                # 提取 total（新格式：分页.总条数）
                pagination = obj.get("分页")
                if isinstance(pagination, dict):
                    t = pagination.get("总条数")
                    if isinstance(t, (int, float)):
                        total = int(t)
                # 旧格式兼容
                for k in ("total", "total_count", "count", "总数"):
                    v = obj.get(k)
                    if isinstance(v, (int, float)):
                        total = int(v)
                        break
                # 递归查找列表（新格式：条目列表，旧格式：items/data/list/records）
                for key in obj:
                    val = obj[key]
                    if isinstance(val, list) and val:
                        return val
                    if isinstance(val, dict):
                        result = _find_list(val, depth + 1)
                        if result is not None:
                            return result
                # 最后拿任何非空list
                for val in obj.values():
                    if isinstance(val, list) and val:
                        return val
            return None

        items = _find_list(data)
        return (items or [], total)

    _source1_response_logged: set = set()
    _hok_response_logged: bool = False

    async def _fetch_source1_page(
        self, data_type: str, page: int = 1, page_size: int = 100, merchant: str = ""
    ) -> dict:
        """调用 public-query 单页，返回 {"items": [...], "total": int|None, "has_next": bool}"""
        if not self.source1_api_key:
            if not self._warned_empty_api_key:
                self._warned_empty_api_key = True
                logger.warning("[居所] ⚠️ 数据源1 x-api-key 未配置，已跳过 public-query 请求，请在WebUI设置 source1_api_key")
            return {"items": None, "total": None, "has_next": False}

        params = {"type": data_type, "page": str(page), "page_size": str(page_size)}
        if merchant:
            params["merchant"] = merchant
        url = f"{self.supabase_url}/functions/v1/public-query?" + "&".join(f"{k}={v}" for k, v in params.items())

        headers = self._build_source1_headers()

        # 频率控制
        import time as _time_mod
        now_ts = _time_mod.time()
        since_last = now_ts - self._source1_last_call
        if since_last < self._source1_min_interval:
            await asyncio.sleep(self._source1_min_interval - since_last)
        self._source1_last_call = _time_mod.time()

        max_retries = 2
        for attempt in range(max_retries + 1):
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 429:
                            logger.warning(f"public-query [429] 限流（attempt {attempt+1}/{max_retries+1}），等待后重试...")
                            if attempt < max_retries:
                                await asyncio.sleep(5 * (attempt + 1))
                                continue
                            return {"items": None, "total": None, "has_next": False}
                        if resp.status != 200:
                            logger.warning(f"public-query [{resp.status}]: {(await resp.text())[:200]}")
                            return {"items": None, "total": None, "has_next": False}
                        data = await resp.json()
                        break
                except Exception as e:
                    logger.warning(f"public-query 请求失败: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(2)
                        continue
                    return {"items": None, "total": None, "has_next": False}

        # 首次打印响应结构
        log_key = f"{data_type}"
        if log_key not in self._source1_response_logged:
            self._source1_response_logged.add(log_key)
            if isinstance(data, dict):
                logger.info(f"[居所] public-query type={data_type} 响应结构: keys={list(data.keys())}")
            elif isinstance(data, list):
                logger.info(f"[居所] public-query type={data_type} 响应结构: 直接列表, len={len(data)}")

        # 提取是否有下一页
        has_next = False
        pagination = data.get("分页") if isinstance(data, dict) else None
        if isinstance(pagination, dict):
            has_next = pagination.get("是否有下一页", False) is True

        raw_items, total = self._extract_items_from_response(data, data_type)
        if raw_items is None:
            return {"items": None, "total": total, "has_next": has_next}
        normalized = [self._normalize_source1_item(it, data_type) for it in raw_items]
        return {"items": normalized, "total": total, "has_next": has_next}

    async def _fetch_source1_all(
        self, data_type: str, merchant: str = "", page_size: int = 100
    ) -> Optional[list]:
        """拉取 public-query 全部页，返回 normalized 列表（带60秒缓存防限流）"""
        import time as _time
        cache_key = f"{data_type}:{merchant}:{page_size}"
        now = _time.time()
        if cache_key in self._source1_result_cache:
            cached_data, cached_time = self._source1_result_cache[cache_key]
            if now - cached_time < self._source1_cache_ttl:
                logger.debug(f"[居所] source1 cache HIT: {cache_key} (age={now - cached_time:.1f}s)")
                return cached_data.copy() if isinstance(cached_data, list) else cached_data

        all_items = []
        page = 1
        total_from_api = None

        while True:
            try:
                result = await self._fetch_source1_page(data_type, page=page, page_size=page_size, merchant=merchant)
            except Exception as e:
                logger.warning(f"public-query _fetch_source1_all 调用失败: {e}\n{traceback.format_exc()}")
                return None if page == 1 else all_items
            if not isinstance(result, dict):
                return None if page == 1 else all_items
            items = result.get("items")
            if items is None:
                return None if page == 1 else all_items

            if total_from_api is None and result.get("total") is not None:
                total_from_api = result["total"]

            if not items:
                break
            all_items.extend(items)

            # 翻页判断：has_next 优先，fallback total/len < page_size
            if result.get("has_next"):
                page += 1
            elif total_from_api is not None:
                if len(all_items) >= total_from_api:
                    break
                page += 1
            elif len(items) < page_size:
                break
            else:
                page += 1

        logger.debug(f"[居所] public-query type={data_type}: 共 {len(all_items)} 条")
        import time as _time2
        self._source1_result_cache[cache_key] = (all_items.copy(), _time2.time())
        return all_items

    # ==================== 源1辅助：牧场产品名缓存（REST API） ====================

    async def _load_ranch_presets(self):
        """从 Supabase REST API 查 ranch_product_presets，缓存 {preset_id: product_name}"""
        if not self.anon_key:
            return
        url = f"{self.supabase_url}/rest/v1/{TABLE_RANCH_PRESETS}?select=id,name"
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://jusuo.playmmo.cn/",
        }
        if self.source1_api_key:
            headers["x-api-key"] = self.source1_api_key
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    # 401 时回退到内置默认 anon key 重试一次（配置里误填了错误 key 的情况）
                    if resp.status == 401 and self.anon_key != DEFAULT_ANON_KEY:
                        headers2 = dict(headers)
                        headers2["apikey"] = DEFAULT_ANON_KEY
                        headers2["Authorization"] = f"Bearer {DEFAULT_ANON_KEY}"
                        async with session.get(url, headers=headers2, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                            if resp2.status == 200:
                                data = await resp2.json()
                                logger.info("[居所] 牧场预设 anon key 无效，已自动回退内置默认密钥")
                            else:
                                logger.warning(f"[居所] ranch presets [{resp2.status}]")
                                return
                    elif resp.status != 200:
                        logger.warning(f"[居所] ranch presets [{resp.status}]")
                        return
                    else:
                        data = await resp.json()
                    if isinstance(data, list):
                        self._ranch_products_cache = {item["id"]: item["name"] for item in data if "id" in item and "name" in item}
                        self._ranch_product_names = sorted(set(self._ranch_products_cache.values()))
                        logger.info(f"[居所] 已加载牧场产品预设 {len(self._ranch_products_cache)} 条")
        except Exception as e:
            logger.warning(f"[居所] ranch presets 加载失败: {e}")

    # ==================== HOK 数据源 ====================

    async def _fetch_hok_items(self, crop_name: str, limit: int = 0) -> Optional[list]:
        """从 hokshijie.online 查询作物条目"""
        if limit <= 0:
            limit = self.hok_items_limit
        url = f"{self.hok_api}/api/items?crop={crop_name}&limit={limit}"
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, ssl=ssl_ctx, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning(f"HOK items [{resp.status}]: {(await resp.text())[:200]}")
                        return None
                    data = await resp.json()
                    # 记录一次响应结构
                    if not self._hok_response_logged:
                        self._hok_response_logged = True
                        if isinstance(data, dict):
                            logger.info(f"[居所] HOK items 响应结构: keys={list(data.keys())}, code={data.get('code')}, "
                                        f"data类型={type(data.get('data')).__name__}")
                            inner = data.get("data", {})
                            if isinstance(inner, dict):
                                for k, v in inner.items():
                                    vtype = type(v).__name__
                                    vlen = len(v) if isinstance(v, (list, dict, str)) else v
                                    logger.info(f"[居所] HOK data.{k}: {vtype}, len={vlen}")
                            elif isinstance(inner, list):
                                logger.info(f"[居所] HOK data: list, len={len(inner)}")
                        else:
                            logger.info(f"[居所] HOK items 响应结构: type={type(data).__name__}")
                    # 兼容两种响应结构：{code:0, data:{items:[...]}} 或 {code:0, data:[...]}
                    if isinstance(data, dict) and data.get("code") == 0:
                        inner_data = data.get("data", {})
                        if isinstance(inner_data, dict):
                            items = inner_data.get("items", [])
                        elif isinstance(inner_data, list):
                            items = inner_data
                        else:
                            items = []
                        logger.debug(f"[居所] HOK crop={crop_name}: 返回 {len(items)} 条 (limit={limit})")
                        return items
                    return data if isinstance(data, list) else None
            except Exception as e:
                logger.warning(f"HOK items 请求失败: {e}\n{traceback.format_exc()}")
                return None

    async def _fetch_hok_furniture(self, limit: int = 0) -> Optional[list]:
        """从 hokshijie.online 查询家具"""
        if limit <= 0:
            limit = self.hok_items_limit
        url = f"{self.hok_api}/api/furniture?limit={limit}"
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, ssl=ssl_ctx, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning(f"HOK furniture [{resp.status}]: {(await resp.text())[:200]}")
                        return None
                    data = await resp.json()
                    # 兼容两种结构：{code:0, data:{items:[...]}} 或 {code:0, data:[...]}
                    if isinstance(data, dict):
                        inner = data.get("data", [])
                        if isinstance(inner, dict):
                            items = inner.get("items", inner)
                        else:
                            items = inner
                        logger.debug(f"[居所] HOK furniture: 返回 {len(items) if isinstance(items, list) else '?'} 条 (limit={limit})")
                        return items if isinstance(items, list) else None
                    return data if isinstance(data, list) else None
            except Exception as e:
                logger.warning(f"HOK furniture 请求失败: {e}\n{traceback.format_exc()}")
                return None

    # ==================== 数据源3: wsjjiayuan.cn ====================

    async def _fetch_wsjj_items(self, crop_name: str) -> Optional[list]:
        """从 wsjjiayuan.cn 查询作物条目"""
        from urllib.parse import quote
        url = f"{self.wsjj_api}/api/farm?crop={quote(crop_name)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning(f"WSJJ items [{resp.status}]: {(await resp.text())[:200]}")
                        return None
                    data = await resp.json()
                    if isinstance(data, dict):
                        items = data.get("items", [])
                        logger.debug(f"[居所] WSJJ crop={crop_name}: 返回 {len(items)} 条")
                        return items
                    return None
            except Exception as e:
                logger.warning(f"WSJJ items 请求失败: {e}\n{traceback.format_exc()}")
                return None

    async def _fetch_wsjj_ranch(self, product_name: str = "") -> Optional[list]:
        """从 wsjjiayuan.cn 查询牧场条目"""
        from urllib.parse import quote
        url = f"{self.wsjj_api}/api/ranch"
        if product_name:
            url += f"?product={quote(product_name)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning(f"WSJJ ranch [{resp.status}]: {(await resp.text())[:200]}")
                        return None
                    data = await resp.json()
                    if isinstance(data, dict):
                        items = data.get("items", [])
                        logger.debug(f"[居所] WSJJ ranch: 返回 {len(items)} 条")
                        return items
                    return None
            except Exception as e:
                logger.warning(f"WSJJ ranch 请求失败: {e}\n{traceback.format_exc()}")
                return None

    async def _fetch_wsjj_furniture(self) -> Optional[list]:
        """从 wsjjiayuan.cn 查询家具条目"""
        url = f"{self.wsjj_api}/api/furniture"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning(f"WSJJ furniture [{resp.status}]: {(await resp.text())[:200]}")
                        return None
                    data = await resp.json()
                    if isinstance(data, dict):
                        items = data.get("items", [])
                        logger.debug(f"[居所] WSJJ furniture: 返回 {len(items)} 条")
                        return items
                    return None
            except Exception as e:
                logger.warning(f"WSJJ furniture 请求失败: {e}\n{traceback.format_exc()}")
                return None

    # ==================== 牧场 / 家具查询 ====================

    async def _query_ranch(self, name: str, gid: str = "") -> str:
        # 数据源开关：群独立 > 全局
        es1 = self._get_group_setting(gid, "enable_source1")
        if es1 is None:
            es1 = self.enable_source1
        es3 = self._get_group_setting(gid, "enable_source3")
        if es3 is None:
            es3 = self.enable_source3

        # 收集所有数据源结果
        all_raw = []

        # 源1
        if es1:
            data = await self._fetch_source1_all("ranch")
            if data:
                all_raw.extend(data)

        # 源3：家园站
        if es3:
            try:
                wsjj_data = await self._fetch_wsjj_ranch()
            except Exception:
                wsjj_data = None
            if wsjj_data:
                all_raw.extend(wsjj_data)

        if not all_raw:
            return "❌ 查询失败"

        # 归一化并过滤
        normalized = []
        seen_uids = set()
        for item in all_raw:
            # 源1 和 源3 字段名可能不同，统一处理
            pn = item.get("product_name") or item.get("productName") or ""
            if not pn:
                continue
            uid = str(item.get("uid", ""))
            if uid in seen_uids:
                continue
            seen_uids.add(uid)
            multiplier = float(item.get("price_multiplier") or item.get("multiplier") or 0)
            quantity = int(item.get("quantity") or 0)
            merchant = item.get("merchant_name") or item.get("merchantName") or "?"
            source = SOURCE1_NAME if "product_name" in item else SOURCE3_NAME
            normalized.append({
                "product_name": pn,
                "uid": uid,
                "price_multiplier": multiplier,
                "quantity": quantity,
                "merchant_name": merchant,
                "source": source,
                "residence_level": int(item.get("residence_level") or item.get("stallLevel") or 1),
                "guild_maxed": bool(item.get("guild_maxed") or item.get("baijiaMax") or False),
                "sale_price": int(item.get("sale_price") or 0),
            })

        # 按产品名称过滤（模糊匹配）
        matched = [item for item in normalized if name in str(item.get("product_name", "")) or str(item.get("product_name", "")) in name]
        if not matched:
            all_names = sorted(set(str(item.get("product_name", "")) for item in normalized if item.get("product_name")))
            if not all_names:
                return f"📭 未找到「{name}」的牧场产品"
            return f"📭 未找到「{name}」的牧场产品\n\n💡 可用产品：\n\n" + "\n\n".join(f"  · {n}" for n in all_names[:30])

        # 取最佳匹配产品名（最短即最精确）
        product_names = list(set(str(item.get("product_name", "")) for item in matched))
        product_names.sort(key=len)
        best_name = product_names[0]

        # 过滤出该产品的条目，排序
        items = [item for item in matched if item.get("product_name") == best_name]
        items.sort(key=lambda x: float(x.get("price_multiplier", 0)), reverse=True)

        ranch_unit_price = self._get_unit_price(best_name)
        return self._format_ranch_result(best_name, [
            {
                "uid": str(item.get("uid", "?")),
                "price_multiplier": float(item.get("price_multiplier", 0)),
                "quantity": int(item.get("quantity", 0)),
                "merchant": item.get("merchant_name", "?"),
                "source": item.get("source", SOURCE1_NAME),
                "unit_price": ranch_unit_price,
                "residence_level": int(item.get("residence_level") or 1),
                "guild_maxed": bool(item.get("guild_maxed") or False),
            }
            for item in items
        ])

    async def _query_furniture(self, name: str, gid: str = "") -> str:
        results = []
        seen = set()
        # 数据源开关：群独立 > 全局
        es1 = self._get_group_setting(gid, "enable_source1")
        if es1 is None:
            es1 = self.enable_source1
        es2 = self._get_group_setting(gid, "enable_source2")
        if es2 is None:
            es2 = self.enable_source2
        es3 = self._get_group_setting(gid, "enable_source3")
        if es3 is None:
            es3 = self.enable_source3
        # 源1 public-query — 全量拉取后客户端过滤
        if es1:
            data = await self._fetch_source1_all("furniture")
            if data:
                for item in data:
                    uid = str(item.get("uid", ""))
                    if uid in seen:
                        continue
                    merchant = str(item.get("merchant_name", ""))
                    fids = item.get("furniture_ids") or []
                    if name in merchant or any(name in str(fid) for fid in fids):
                        seen.add(uid)
                        results.append({
                            "uid": uid,
                            "merchant": merchant,
                            "likes": item.get("like_count", 0),
                            "furniture_list": fids,
                            "source": SOURCE1_NAME,
                        })
        # 源2 hok — 同时匹配merchant和furniture_list
        if es2:
            data = await self._fetch_hok_furniture()
            if data:
                for item in data:
                    uid = str(item.get("uid", ""))
                    if uid in seen:
                        continue
                    merchant = item.get("merchant", "")
                    flist = item.get("furniture_list") or []
                    if name in merchant or any(name in str(f) for f in flist):
                        seen.add(uid)
                        results.append({
                            "uid": uid,
                            "merchant": merchant,
                            "likes": 0,
                            "furniture_list": flist,
                            "source": SOURCE2_NAME,
                        })
        # 源3 家园站 — 家具
        if es3:
            try:
                data = await self._fetch_wsjj_furniture()
            except Exception:
                data = None
            if data:
                for item in data:
                    uid = str(item.get("uid", ""))
                    if uid in seen:
                        continue
                    merchant = item.get("merchantName") or item.get("merchant", "")
                    flist = item.get("furnitureList") or item.get("furniture_list") or []
                    if name in merchant or any(name in str(f) for f in flist):
                        seen.add(uid)
                        results.append({
                            "uid": uid,
                            "merchant": merchant,
                            "likes": 0,
                            "furniture_list": flist,
                            "source": SOURCE3_NAME,
                        })

        if not results:
            return f"📭 未找到「{name}」的家具分享"

        recall_hint = f" · {self.recall_seconds}s撤回" if self.recall_seconds > 0 else ""
        lines = [f"🪑 {name} · 家具分享{recall_hint}\n\n共{len(results)}条"]
        for i, item in enumerate(results[:5]):
            furn_preview = "、".join(item["furniture_list"][:3]) if item["furniture_list"] else "-"
            lines.append(
                f"  {i+1}. {item['merchant']}\n\n     UID {item['uid'][:12]}  家具: {furn_preview}"
            )
        return "\n\n".join(lines)

    # ==================== Playwright 家具图鉴渲染 ====================

    def _build_furniture_html(self) -> str:
        """生成家具图鉴 HTML"""
        cards = []
        total_count = 0
        for merchant in KNOWN_MERCHANTS:
            mf_map = MERCHANT_FURNITURE_MAP.get(merchant, {})
            if not mf_map:
                continue
            all_names = [n for names in mf_map.values() for n in names]
            total_count += len(all_names)
            sections = []
            for quality, items in mf_map.items():
                color_class = {
                    "紫色品质": "purple",
                    "蓝色品质": "blue",
                    "绿色品质": "green",
                }.get(quality, "blue")
                sections.append(
                    f'<div class="quality-row">'
                    f'<span class="badge badge-{color_class}">{quality}</span>'
                    f'<span class="items">{"、".join(items)}</span>'
                    f'</div>'
                )
            cards.append(
                f'<div class="card">'
                f'<div class="card-header">▸ {merchant}<span class="count">{len(all_names)}件</span></div>'
                f'{"".join(sections)}'
                f'</div>'
            )
        return textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head><meta charset="UTF-8">
          <link rel="preconnect" href="https://fonts.loli.net">
          <link rel="preconnect" href="https://gstatic.loli.net" crossorigin>
          <link href="https://fonts.loli.net/css2?family=Noto+Sans+SC:wght@400;700&display=swap" rel="stylesheet">
        <style>
          /* @font-face 备选方案：若 Google Fonts 不可访问，尝试镜像站或系统字体 */
          @font-face {{
            font-family: "Noto Sans SC Fallback";
            src: local("Microsoft YaHei"), local("PingFang SC"), local("Noto Sans CJK SC"), local("SimHei");
          }}
          * {{ margin: 0; padding: 0; box-sizing: border-box; }}
          body {{ font-family: "Noto Sans SC", "Noto Sans SC Fallback", "Microsoft YaHei", "PingFang SC", "SimHei", sans-serif; background: linear-gradient(135deg, #ede7dd 0%, #f5f0e8 50%, #ede7dd 100%); padding: 40px 36px; }}
          .page {{ max-width: 900px; margin: 0 auto; }}
          .header {{ text-align: center; margin-bottom: 32px; padding-bottom: 24px; border-bottom: 2px solid #d7ccc8; }}
          .title {{ font-size: 34px; font-weight: bold; color: #4e342e; letter-spacing: 2px; margin-bottom: 8px; }}
          .subtitle {{ font-size: 16px; color: #8d6e63; letter-spacing: 1px; }}
          .subtitle strong {{ color: #5d4037; }}
          .card {{ background: #fff; border-radius: 16px; padding: 24px 28px; margin-bottom: 20px; box-shadow: 0 4px 16px rgba(0,0,0,0.07); border-left: 4px solid #bc8a5f; transition: none; }}
          .card:nth-child(2) {{ border-left-color: #8d6e63; }}
          .card:nth-child(3) {{ border-left-color: #a1887f; }}
          .card:nth-child(4) {{ border-left-color: #bcaaa4; }}
          .card:nth-child(5) {{ border-left-color: #d7ccc8; }}
          .card-header {{ font-size: 22px; font-weight: bold; color: #3e2723; margin-bottom: 14px; display: flex; align-items: center; gap: 10px; }}
          .card-header .icon {{ font-size: 24px; }}
          .count {{ font-size: 14px; font-weight: normal; color: #a1887f; margin-left: 8px; }}
          .quality-row {{ display: flex; align-items: flex-start; gap: 12px; margin-bottom: 12px; }}
          .quality-row:last-child {{ margin-bottom: 0; }}
          .badge {{ flex-shrink: 0; display: inline-block; padding: 3px 14px; border-radius: 12px; font-size: 14px; font-weight: bold; line-height: 22px; white-space: nowrap; }}
          .badge-purple {{ background: #f3e5f5; color: #6a1b9a; }}
          .badge-blue {{ background: #e3f2fd; color: #1565c0; }}
          .badge-green {{ background: #e8f5e9; color: #2e7d32; }}
          .items {{ font-size: 17px; color: #4e342e; line-height: 2.0; }}
          .footer {{ text-align: center; font-size: 14px; color: #bcaaa4; margin-top: 28px; padding-top: 20px; border-top: 1px solid #efebe9; }}
        </style></head>
        <body>
          <div class="page">
            <div class="header">
              <div class="title">王世杰居所 · 家具图鉴</div>
              <div class="subtitle">共 <strong>{len(KNOWN_MERCHANTS)}</strong> 位商人  ·  <strong>{total_count}</strong> 件家具</div>
            </div>
            {"".join(cards)}
            <div class="footer">数据来源：jusuo.playmmo.cn · hokshijie.online</div>
          </div>
        </body></html>""")

    async def _generate_furniture_image(self) -> str:
        """用 Playwright 渲染家具图鉴为 PNG，返回图片路径"""
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("[居所] Playwright 未安装，无法生成家具图鉴图片")
            return ""

        html = self._build_furniture_html()

        img_dir = os.path.join(tempfile.gettempdir(), "jusuo_images")
        os.makedirs(img_dir, exist_ok=True)
        img_path = os.path.join(img_dir, "furniture_list.png")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                page = await browser.new_page(viewport={"width": 940, "height": 100})
                await page.set_content(html, wait_until="networkidle", timeout=30000)
                # 等待所有 web 字体加载完毕，避免中文字符渲染为方框（tofu）
                try:
                    await page.evaluate("document.fonts.ready")
                except Exception:
                    pass
                # 额外等待 500ms 确保字体渲染完成
                await page.wait_for_timeout(500)
                # 计算实际内容高度
                body_height = await page.evaluate("document.body.scrollHeight")
                await page.set_viewport_size({"width": 940, "height": body_height + 20})
                await page.screenshot(path=img_path, full_page=True)
                await browser.close()
            logger.info(f"[居所] 家具图鉴已生成: {img_path}")
            return img_path
        except Exception as e:
            logger.error(f"[居所] Playwright 渲染失败: {e}")
            return ""

    async def _send_image_to_group(self, event: AstrMessageEvent, image_path: str, label: str = "图片") -> bool:
        """通过 adapter 发送图片到群聊（仅 QQ 群），返回是否成功。

        发送策略：优先 base64 内联（图片字节随消息直接传给 onebot 端，adapter
        侧无需解析文件路径，彻底规避 AstrBot(Linux/WSL) 与 napcat(Windows) 跨
        环境时 file:// 路径在宿主侧 stat 不到的 ENOENT 问题）；file:// 仅作兜底。
        """
        gid = self._get_group_id(event)
        if not gid or not gid.isdigit():
            return False

        # 查找 adapter（复用 _send_result 逻辑）
        adapter = None
        for src in (event.message_obj, event):
            for attr_name in ('_adapter', 'adapter', '_bot', 'bot', '_client', 'client', '_platform', 'platform'):
                val = getattr(src, attr_name, None)
                if val and hasattr(val, 'api') and hasattr(val.api, 'send_group_msg'):
                    adapter = val
                    break
            if adapter:
                break
        if not adapter:
            adapter = await self._find_broadcast_adapter()

        if not adapter:
            logger.warning(f"[居所] {label}：未找到 adapter，无法发送图片")
            return False

        self._cached_adapter = adapter
        api = getattr(adapter, 'api', None)
        send_fn = getattr(api, 'send_group_msg', None) if api else None
        if not send_fn:
            send_fn = getattr(adapter, 'send_group_msg', None)
        if not send_fn:
            return False

        # 1) 优先 base64 内联（跨环境最稳，adapter 无需访问本地文件）
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            img_segment = {"type": "image", "data": {"file": f"base64://{b64}"}}
            await send_fn(group_id=self._to_group_id(gid), message=[img_segment])
            logger.info(f"[居所] {label}已通过 base64 发送到群 {gid}")
            return True
        except Exception as e:
            logger.warning(f"[居所] {label} base64 发送失败: {e}，尝试 file://")

        # 2) 兜底 file://（要求 adapter 与图片同文件系统）
        try:
            if image_path.startswith("/"):
                file_uri = f"file://{image_path}"
            else:
                file_uri = f"file:///{image_path.replace(os.sep, '/')}"
            img_segment = {"type": "image", "data": {"file": file_uri}}
            await send_fn(group_id=self._to_group_id(gid), message=[img_segment])
            logger.info(f"[居所] {label}已通过 file:// 发送到群 {gid}")
            return True
        except Exception as e:
            logger.warning(f"[居所] {label}发送失败: {e}")
            return False

    # ---- 「状态」指令：完整数据页面（HTML→图片） ----
    def _build_status_html(self) -> str:
        """生成「状态」指令的完整数据页 HTML（数据内嵌，无需 bridge），样式匹配浅蓝玻璃主题"""
        from datetime import datetime as _dt
        ver = "1.12"
        date_since = getattr(self, "version_date", "2026-07-12")
        on_mark = lambda c: "✅" if c else "❌"

        # —— 运行概览 ——
        total_map = self._crop_query_counts.get("total", {}) or {}
        total_q = sum(total_map.values())
        top_crop, top_n = "", 0
        if total_map:
            top_crop, top_n = max(total_map.items(), key=lambda kv: kv[1])
        录入 = sum(len(v) for v in self._录入_records.get("uids", {}).values())

        # —— 配置速览 ——
        def cfg_row(ic, label, on=None, val=None):
            if on is None:
                st = '<span class="st val">' + str(val) + '</span>'
            elif on:
                st = '<span class="st on">已开启' + ((" · " + str(val)) if val else "") + '</span>'
            else:
                st = '<span class="st off">已关闭</span>'
            return ('<div class="cfg-item"><span class="cfg-ic">' + ic + '</span>'
                    '<span class="cfg-lb">' + label + '</span>' + st + '</div>')

        rl_w = int(getattr(self, "_qq_rate_limit_window", 600)) // 60
        rl_m = int(getattr(self, "_qq_rate_limit_max", 3))
        grp_n = len(getattr(self, "_group_settings", {}))
        cfg_html = (
            cfg_row("🏠", "源1 · 居所站", self.enable_source1)
            + cfg_row("🌐", "源2 · HOK站", self.enable_source2)
            + cfg_row("🏡", "源3 · 家园站", self.enable_source3)
            + cfg_row("🔄", "后台轮询播报", self.polling_enabled)
            + cfg_row("↩️", "查询结果撤回", self.recall_seconds > 0, (str(self.recall_seconds) + "s") if self.recall_seconds > 0 else None)
            + cfg_row("⏱️", "轮询间隔", None, "每" + str(self.poll_interval_minutes) + "分钟")
            + cfg_row("🌱", "监控作物", None, str(len(self.poll_crop_filter & set(KNOWN_CROPS))) + " 种")
            + cfg_row("💬", "自定义回复", bool(self.custom_reply))
            + cfg_row("🚦", "QQ查询限流", None, str(rl_w) + "分钟" + str(rl_m) + "次")
            + cfg_row("👥", "群独立配置", None, str(grp_n) + " 个群")
            + cfg_row("🌾", "白名单·作物播报", bool(getattr(self, "whitelist_crop_detect", False)))
            + cfg_row("📣", "白名单·@回复", bool(getattr(self, "whitelist_at_reply", False)))
        )

        # —— 各作物播报阈值 ——
        thr_html = ""
        for _c in KNOWN_CROPS:
            _t = int(self._poll_thresholds.get(_c, DEFAULT_POLL_THRESHOLDS.get(_c, 9990000)))
            thr_html += ('<div class="thr-item"><span class="thr-nm">🌾 ' + _c
                        + '</span><span class="thr-val">≥' + str(_t // 10000) + '万</span></div>')

        # —— 历史最高价（按 ts 降序，显示全部记录，与仪表盘一致）——
        # 百工币严格格式：3位整数补零+1位小数（000.0），与仪表盘 renderHigh fmtBgb 一致
        def _fmt_bgb(_v):
            try:
                _n = float(_v)
                _s = f"{_n:.1f}"
                _p = _s.split(".")
                return _p[0].zfill(3) + "." + _p[1]
            except (ValueError, TypeError):
                return str(_v)
        def _fmt_date_short(_ts):
            """短日期 MM-DD，与仪表盘 fmtDate 一致"""
            if not _ts:
                return ""
            return _dt.fromtimestamp(int(_ts)).strftime("%m-%d")
        highs = sorted(self._high_records.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)
        high_html = ""
        for _c, _rec in highs:
            _inc = _rec.get("income_str", "?")
            _qty = _rec.get("quantity", 0)
            _ts = _rec.get("ts", 0)
            _dt_str = _fmt_date_short(_ts) or "—"
            high_html += ('<div class="hi"><span class="nm">' + _c + '</span>'
                         '<span class="inc">' + _fmt_bgb(_inc) + '</span>'
                         '<span class="sub">' + str(_qty) + '</span>'
                         '<span class="dt">' + _dt_str + '</span></div>')

        # —— 作物查询热度（total 降序 top8）——
        heat = sorted(total_map.items(), key=lambda kv: kv[1], reverse=True)[:8]
        _maxc = max((_n for _c, _n in heat), default=1) or 1
        heat_html = ""
        for _c, _n in heat:
            _pct = int(_n / _maxc * 100)
            heat_html += ('<div class="bar"><div class="top"><span class="nm">🌾 ' + _c + '</span>'
                         '<span class="ct">' + str(_n) + ' 次</span></div>'
                         '<div class="track"><div class="fill" style="width:' + str(_pct) + '%"></div></div></div>')

        # —— 统计卡（3 张）——
        stat2_lbl = ("查询最多的作物 · " + str(top_n) + " 次") if top_crop else "查询最多的作物"
        stats_html = (
            '<div class="stat"><span class="num">' + str(total_q) + '</span><span class="lbl">累计查询次数</span></div>'
            '<div class="stat"><span class="num">' + (top_crop or "暂无") + '</span><span class="lbl">' + stat2_lbl + '</span></div>'
            '<div class="stat"><span class="num">' + str(录入) + '</span><span class="lbl">已录入数据</span></div>'
        )

        # —— 当前插件 logo（本地 logo.png，运行时 base64 内嵌进图片 HTML，离线出图也稳定）——
        _logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        _logo_uri = ""
        try:
            with open(_logo_path, "rb") as _lf:
                _logo_uri = "data:image/png;base64," + base64.b64encode(_lf.read()).decode("ascii")
        except Exception:
            _logo_uri = ""
        _logo_html = ('<img class="logo" alt="王世杰居所助手" src="' + _logo_uri + '">') if _logo_uri else '<div class="logo fallback">🏯</div>'

        css = "<style>" + status_font_face_css() + """
      * { margin:0; padding:0; box-sizing:border-box; }
      body { font-family:"JusuoEmoji","JusuoCJK","Noto Sans SC","Microsoft YaHei","PingFang SC",sans-serif;
        background:linear-gradient(135deg,#eaf3fb 0%,#f4f9ff 50%,#eaf3fb 100%);
        padding:36px 32px; color:#1f3a5a; }
      .page { max-width:880px; margin:0 auto; }
      .hero { display:flex; align-items:center; gap:16px; padding:18px 22px; border-radius:18px;
        background:linear-gradient(135deg,rgba(255,255,255,.78),rgba(255,255,255,.5));
        border:1px solid rgba(56,189,248,.35); box-shadow:0 10px 30px rgba(47,127,240,.12), inset 0 1px 0 rgba(255,255,255,.8);
        margin-bottom:18px; }
      .hero .logo { width:54px; height:54px; border-radius:14px; object-fit:contain;
        box-shadow:0 4px 14px rgba(47,127,240,.25); }
      .hero .logo.fallback { display:flex; align-items:center; justify-content:center; font-size:28px;
        background:linear-gradient(135deg,#2f7ff0,#38bdf8); object-fit:initial; box-shadow:none; }
      .hero h1 { font-size:21px; font-weight:800; color:#1f3a5a; }
      .hero .sub { font-size:12px; color:#5b7da3; margin-top:3px; }
      .badge { margin-left:auto; align-self:center; font-size:12px; font-weight:700; color:#fff;
        background:linear-gradient(135deg,#2f7ff0,#38bdf8); padding:5px 12px; border-radius:999px; }
      .sec-title { font-size:14px; font-weight:800; color:#1f3a5a; margin:18px 4px 10px; display:flex; align-items:center; gap:8px; }
      .sec-title .dot { width:8px; height:8px; border-radius:50%; background:#2f7ff0; }
      .hint { color:#5b7da3; font-size:11px; font-weight:400; margin-left:8px; }
      .two-col { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
      .col { min-width:0; }
      .card { background:linear-gradient(135deg,rgba(255,255,255,.72),rgba(255,255,255,.42));
        border:1px solid rgba(56,189,248,.28); border-radius:16px; padding:16px 18px;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.8), 0 6px 18px rgba(47,127,240,.08); }
      .stats { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
      .stat { background:linear-gradient(135deg,rgba(255,255,255,.72),rgba(255,255,255,.42));
        border:1px solid rgba(56,189,248,.28); border-radius:14px; padding:14px 16px; text-align:center; }
      .stat .num { display:block; font-size:24px; font-weight:800; color:#2f7ff0; font-variant-numeric:tabular-nums; }
      .stat .lbl { display:block; font-size:11.5px; color:#5b7da3; margin-top:4px; }
      .cfg { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
      .cfg-item { display:flex; align-items:center; gap:8px; padding:10px 12px; border-radius:12px;
        background:rgba(255,255,255,.5); border:1px solid rgba(56,189,248,.22); }
      .cfg-ic { font-size:15px; }
      .cfg-lb { flex:1; min-width:0; font-size:12.5px; font-weight:600; color:#1f3a5a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .st { display:inline-flex; align-items:center; gap:5px; font-size:11px; padding:2px 8px; border-radius:999px; white-space:nowrap; }
      .st.on { color:#2f7ff0; background:rgba(56,189,248,.16); }
      .st.off { color:#e0457b; background:rgba(224,69,123,.10); }
      .st.val { color:#2f7ff0; background:rgba(56,189,248,.13); font-weight:600; }
      .thr { margin-top:14px; padding-top:12px; border-top:1px dashed rgba(56,189,248,.35); }
      .thr-h { font-size:12.5px; font-weight:700; color:#1f3a5a; margin-bottom:8px; }
      .thr-sub { font-size:10.5px; font-weight:500; color:#5b7da3; }
      .thr-list { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
      .thr-item { display:flex; align-items:center; justify-content:space-between; gap:6px; padding:8px 10px; border-radius:10px;
        background:rgba(255,255,255,.5); border:1px solid rgba(56,189,248,.22); }
      .thr-nm { font-size:12px; font-weight:600; color:#1f3a5a; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .thr-val { font-size:12px; font-weight:700; color:#2f7ff0; white-space:nowrap; font-variant-numeric:tabular-nums; }
      .hi-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr); gap:7px 12px; align-items:center; }
      .hi { display:contents; }
      .hi-head { display:contents; border-bottom:2px solid rgba(47,127,240,.18); margin-bottom:4px; }
      .hi-head > span { font-size:12px; font-weight:700; color:#5b7da3; letter-spacing:.04em; padding-bottom:8px; text-align:left; }
      .hi > .nm { font-size:13px; font-weight:600; color:#1f3a5a; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding:6px 0; text-align:left; }
      .hi > .inc { font-size:15px; font-weight:700; color:#2f7ff0; font-variant-numeric:tabular-nums; text-align:left; white-space:nowrap; padding:6px 0; font-family:"Courier New",Consolas,monospace; letter-spacing:.02em; }
      .hi > .sub { font-size:13px; color:#1f3a5a; font-variant-numeric:tabular-nums; text-align:left; white-space:nowrap; padding:6px 0; font-family:"Courier New",Consolas,monospace; }
      .hi > .dt { font-size:12px; color:#5b7da3; text-align:left; white-space:nowrap; padding:6px 0; }
      .bar { margin:9px 0; }
      .bar .top { display:flex; align-items:center; gap:10px; }
      .bar .nm { color:#1f3a5a; font-weight:500; flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12.5px; }
      .bar .ct { color:#2f7ff0; font-weight:600; font-variant-numeric:tabular-nums; flex:0 0 auto; white-space:nowrap; font-size:12.5px; }
      .bar .track { height:8px; border-radius:999px; background:rgba(120,160,200,.18); overflow:hidden; margin-top:5px; }
      .bar .fill { height:100%; border-radius:999px; background:linear-gradient(90deg,#2f7ff0,#38bdf8); }
      .footer { text-align:center; color:#5b7da3; font-size:11px; margin-top:24px; }
    </style>"""

        return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">""" + css + """</head>
<body><div class="page">
  <div class="hero">
    """ + _logo_html + """
    <div><h1>王世杰居所助手</h1><div class="sub">王者荣耀世界 · 居所收购查询 · 作者 亭子ww</div></div>
    <span class="badge">v""" + ver + """</span>
  </div>

  <div class="sec-title"><span class="dot"></span>运行概览<span class="hint">数据自 """ + date_since + """ 起</span></div>
  <div class="card"><div class="stats">""" + stats_html + """</div></div>

  <div class="sec-title"><span class="dot"></span>配置速览</div>
  <div class="card"><div class="cfg">""" + cfg_html + """</div>
    <div class="thr"><div class="thr-h">各作物播报阈值<span class="thr-sub">　收益 ≥ 此值才触发自动播报（百工币）</span></div><div class="thr-list">""" + thr_html + """</div></div>
  </div>

  <div class="two-col">
    <div class="col">
      <div class="sec-title"><span class="dot"></span>历史最高价</div>
      <div class="card"><div class="hi-grid"><div class="hi-head"><span>作物</span><span>最高价</span><span>数量</span><span>日期</span></div>""" + high_html + """</div></div>
    </div>
    <div class="col">
      <div class="sec-title"><span class="dot"></span>作物查询热度</div>
      <div class="card">""" + heat_html + """</div>
    </div>
  </div>

  <div class="footer">王世杰居所助手 · 状态快照</div>
</div></body></html>"""

    async def _generate_status_image(self) -> str:
        """用 Playwright 渲染「状态」完整数据页为 PNG，返回图片路径（无 chromium 返回空串）"""
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("[居所] Playwright 未安装，无法生成状态图片")
            return ""
        html = self._build_status_html()
        img_dir = os.path.join(tempfile.gettempdir(), "jusuo_images")
        os.makedirs(img_dir, exist_ok=True)
        img_path = os.path.join(img_dir, "status.png")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                page = await browser.new_page(viewport={"width": 940, "height": 100})
                await page.set_content(html, wait_until="networkidle", timeout=30000)
                try:
                    await page.evaluate("document.fonts.ready")
                except Exception:
                    pass
                await page.wait_for_timeout(500)
                body_height = await page.evaluate("document.body.scrollHeight")
                await page.set_viewport_size({"width": 940, "height": body_height + 20})
                await page.screenshot(path=img_path, full_page=True)
                await browser.close()
            logger.info(f"[居所] 状态图片已生成: {img_path}")
            return img_path
        except Exception as e:
            logger.error(f"[居所] 状态图片 Playwright 渲染失败: {e}")
            return ""

    @staticmethod
    def _text_to_markdown(text: str) -> str:
        """将格式化文本转为 Markdown，适配 Snow Markdown 消息段"""
        lines = text.split("\n")
        if not lines:
            return ""
        md_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                md_lines.append("")
                continue
            # 分隔线
            if stripped.startswith("━━"):
                md_lines.append("---")
                continue
            # Item 子行（UID 等）→ 灰色小字
            if line.startswith("     ") and not stripped.startswith(("🥇", "🥈", "🥉")):
                md_lines.append(f"`{stripped}`")
                continue
            # 奖牌行
            if stripped.startswith(("🥇", "🥈", "🥉")):
                md_lines.append(f"**{stripped}**")
                continue
            md_lines.append(stripped)
        return "\n\n".join(md_lines)

    def _cache_adapter_from_event(self, event: AstrMessageEvent):
        """从事件中提取 adapter 并缓存（供轮询广播使用）"""
        if getattr(self, '_cached_adapter', None):
            return  # 已缓存，无需重复提取
        for src in (event.message_obj, event):
            for attr_name in ('_adapter', 'adapter', '_bot', 'bot', '_client', 'client', '_platform', 'platform'):
                val = getattr(src, attr_name, None)
                if val and hasattr(val, 'api') and hasattr(val.api, 'send_group_msg'):
                    self._cached_adapter = val
                    logger.info(f"[居所] 从事件缓存 adapter（供广播使用）")
                    return
                if val and hasattr(val, 'send_group_msg'):
                    self._cached_adapter = val
                    logger.info(f"[居所] 从事件缓存 adapter（供广播使用）")
                    return

    async def _find_broadcast_adapter(self):
        """查找可用的广播 adapter（优先缓存）"""
        if getattr(self, '_cached_adapter', None):
            return self._cached_adapter

        # 尝试 ncatbot BotAPI
        try:
            from ncatbot.client import get_bot
            bot = get_bot()
            api = getattr(bot, 'api', None)
            if api and hasattr(api, 'send_group_msg'):
                self._cached_adapter = bot
                return bot
        except Exception:
            pass

        # 尝试 platform_manager
        try:
            mgr = getattr(self.context, 'platform_manager', None)
            if mgr:
                platforms = None
                for method in ('get_platforms', 'get_instances', 'platforms', 'get_all_platforms'):
                    val = getattr(mgr, method, None)
                    if callable(val):
                        try:
                            platforms = val()
                        except Exception:
                            continue
                    elif isinstance(val, (list, dict)):
                        platforms = val
                    if platforms:
                        break
                if platforms:
                    if isinstance(platforms, dict):
                        platforms = platforms.values()
                    for plat in platforms:
                        adapter = getattr(plat, 'adapter', None) or getattr(plat, 'bot', None) or getattr(plat, 'client', None)
                        if adapter and hasattr(adapter, 'api') and hasattr(adapter.api, 'send_group_msg'):
                            self._cached_adapter = adapter
                            return adapter
        except Exception:
            pass
        return None

    @staticmethod
    def _beijing_time_str() -> str:
        """返回当前北京时间 12小时制字符串"""
        now = datetime.now(timezone(timedelta(hours=8)))
        hour = now.hour
        ampm = "上午" if hour < 12 else "下午"
        display_hour = hour if 1 <= hour <= 12 else (hour - 12 if hour > 12 else 12)
        return f"🕐 北京时间 {ampm} {display_hour}:{now.strftime('%M:%S')}"

    async def _send_result(self, event: AstrMessageEvent, text: str, recall_after: int = 0):
        """群聊拆 text segment 数组直发 adapter → 私聊 plain_result
        recall_after > 0 时，发送后 N 秒自动撤回（仅 QQ 群 adapter 路径）"""
        gid = self._get_group_id(event)

        # 追加当前北京时间
        text = text.rstrip("\n") + f"\n\n{self._beijing_time_str()}"

        # 仅 QQ 群（纯数字 gid）需要拆 segment 绕过管道，微信等平台走正常 plain_result
        if gid and gid.isdigit():
            payload = []
            for chunk in text.split("\n"):
                if payload:
                    payload.append({"type": "text", "data": {"text": "\n"}})
                payload.append({"type": "text", "data": {"text": chunk}})

            # 尝试从 event.message_obj 或 event 上找 adapter
            adapter = None
            for src in (event.message_obj, event):
                for attr_name in ('_adapter', 'adapter', '_bot', 'bot', '_client', 'client', '_platform', 'platform'):
                    val = getattr(src, attr_name, None)
                    if val and hasattr(val, 'api') and hasattr(val.api, 'send_group_msg'):
                        adapter = val
                        break
                if adapter:
                    break

            # 如果直接从 event 找不到，通过 _find_broadcast_adapter
            if not adapter:
                adapter = await self._find_broadcast_adapter()

            if adapter:
                # 缓存找到的 adapter（供广播使用）
                self._cached_adapter = adapter
                try:
                    logger.info(f"[居所] 群聊通过 adapter 直发 gid={gid} segments={len(payload)}")
                    api = getattr(adapter, 'api', None)
                    send_result = None
                    if api and hasattr(api, 'send_group_msg'):
                        send_result = await api.send_group_msg(group_id=self._to_group_id(gid), message=payload)
                    elif hasattr(adapter, 'send_group_msg'):
                        send_result = await adapter.send_group_msg(group_id=self._to_group_id(gid), message=payload)
                    # 必须 yield 一个结果以通知框架消息已处理，否则框架可能只记录日志而不实际发送
                    yield event.plain_result("")
                    # 自动撤回
                    if recall_after > 0 and send_result:
                        msg_id = None
                        if isinstance(send_result, dict):
                            msg_id = send_result.get("message_id") or send_result.get("messageId")
                        else:
                            msg_id = getattr(send_result, "message_id", None) or getattr(send_result, "messageId", None)
                        if msg_id:
                            asyncio.create_task(self._recall_after(adapter, msg_id, recall_after))
                    return
                except Exception as e:
                    logger.warning(f"[居所] adapter.send_group_msg 失败：{e}")
            else:
                logger.warning(f"[居所] 未找到可用的 adapter，回退 plain_result")

        # 私聊/回退：plain_result
        yield event.plain_result(text)

    async def _recall_after(self, adapter, msg_id: int, delay: int):
        """延迟撤回消息"""
        try:
            await asyncio.sleep(delay)
            api = getattr(adapter, 'api', None)
            if api and hasattr(api, 'delete_msg'):
                await api.delete_msg(message_id=msg_id)
            elif hasattr(adapter, 'delete_msg'):
                await adapter.delete_msg(message_id=msg_id)
            else:
                logger.debug(f"[居所] adapter 不支持 delete_msg，跳过撤回")
        except Exception as e:
            logger.debug(f"[居所] 撤回失败 msg_id={msg_id}: {e}")

    # ==================== 缓存 ====================

    async def _ensure_unit_prices(self):
        import time
        now = time.time()
        if self._unit_prices_cache and (now - self._cache_time) < 300:
            return
        data = await self._fetch_supabase(TABLE_UNIT_PRICES, limit=100)
        if data:
            self._unit_prices_cache = {
                item["name"]: item.get("unit_price", 0) for item in data
            }
            self._cache_time = now

    async def _ensure_ranch_products(self):
        """从 public-query ranch 拉取全部牧场产品名缓存（用于列表展示/匹配）"""
        import time
        now = time.time()
        if self._ranch_product_names and (now - self._cache_time) < 600:
            return
        data = await self._fetch_source1_all("ranch")
        if data:
            # 从 ranch 条目中提取去重产品名
            name_set = set()
            for item in data:
                pn = str(item.get("product_name", "")).strip()
                if pn:
                    name_set.add(pn)
            self._ranch_product_names = sorted(name_set, key=len, reverse=True)
            self._ranch_products_cache = {pn: pn for pn in self._ranch_product_names}  # 兼容旧字段（不再需要UUID）
            self._cache_time = now
            logger.info(f"[居所] 牧场产品缓存已加载 {len(self._ranch_product_names)} 个：{self._ranch_product_names}")

    async def _ensure_furniture_names(self):
        """从本地缓存加载全部家具物品名（无需API请求）"""
        if self._furniture_names:
            return  # 模块级常量，无需刷新
        self._furniture_names = _ALL_FURNITURE_NAMES.copy()
        logger.info(f"[居所] 家具名缓存已加载 {len(self._furniture_names)} 个（本地缓存）")

    def _get_unit_price(self, crop_name: str) -> int:
        return self._unit_prices_cache.get(crop_name, 0)

    def _calc_item_income(self, item: dict) -> tuple:
        """计算百工币收入，返回 (income_float, income_str)。

        源1 REST API 数据已含 sale_price，优先使用；
        源2/3 数据不含 sale_price，走手动计算。
        """
        # 优先使用 API 已算好的 sale_price
        sale_price = item.get("sale_price")
        if sale_price and int(sale_price) > 0:
            income = int(sale_price)
            wan = income / 10000
            if wan >= 10:
                income_str = f"{wan:.0f}万"
            elif wan >= 1:
                income_str = f"{wan:.1f}万"
            else:
                income_str = f"{wan:.2f}万"
            return income, income_str

        # fallback：手动计算
        qty = int(item.get("quantity", 0))
        mult = float(item.get("price_multiplier", 0))
        unit_price = int(item.get("unit_price", 0)
                         or item.get("unit_price_val", 0)
                         or self._get_unit_price(str(item.get("crop_name", "") or item.get("name", ""))))
        stall_lv = int(item.get("stall_level", 0)
                       or item.get("residence_level", 0)
                       or item.get("home_level", 0)
                       or 1)
        stall_mult = 1.0 + (stall_lv - 1) * 0.05
        guild_bonus = 1.20 if (item.get("guild_maxed") or item.get("home_max_level", "") == "是") else 1.0
        try:
            income = qty * unit_price * mult * stall_mult * guild_bonus
            wan = income / 10000
            if wan >= 10:
                income_str = f"{wan:.0f}万"
            elif wan >= 1:
                income_str = f"{wan:.1f}万"
            else:
                income_str = f"{wan:.2f}万"
        except (ValueError, TypeError):
            income = 0
            income_str = "?"
        return income, income_str

    # ==================== 格式化输出 ====================

    def _format_crop_result(self, crop_name: str, data: list) -> str:
        total = len(data)

        # 为每条数据计算百工币收入并缓存到 item 中
        for item in data:
            income, income_str = self._calc_item_income(item)
            item["_income"] = income
            item["_income_str"] = income_str

        # 按百工币收入降序排序
        data.sort(key=lambda x: x.get("_income", 0), reverse=True)
        display_count = min(total, 5)

        recall_hint = f" · {self.recall_seconds}s撤回" if self.recall_seconds > 0 else ""
        lines = [f"🌾 {crop_name} · 收购分享{recall_hint}"]
        rec = None
        if crop_name in KNOWN_CROPS:
            real_crop = data[0]["crop_name"] if data else crop_name
            rec = self._high_records.get(real_crop) or self._high_records.get(crop_name)
        if rec:
            qty = rec.get("quantity", 0)
            inc = rec.get("income_str", "?")
            ts = rec.get("ts", 0)
            date_str = f" 📅 {time.strftime('%m-%d', time.localtime(ts))}" if ts else ""
            lines.append("")
            lines.append(f"🏆 最高  📦{qty}  💰{inc}万{date_str}")
        elif data:
            lines.append("")
            lines.append("🏆 最高  📦xxx  💰xxx万")
        lines.append("")
        lines.append(f"共{total}条 | 按百工币↓ | 多源合并")
        header = "\n".join(lines)

        items = []
        for i, item in enumerate(data[:display_count]):
            uid = str(item["uid"])[:12]
            mult = item["price_multiplier"]
            qty = item["quantity"]
            income_str = item.get("_income_str", "?")

            rank = f"{i+1:>2}."
            mult_str = f"✨x{mult:.1f}"
            qty_str = f"×{qty}"

            items.append(
                f"{rank} 💰{income_str:>5}百工币  {mult_str}  {qty_str}\n\n     UID {uid}"
            )

        body = "\n\n".join(items)
        footer = f"\n\n━━ 仅显示前{display_count}条" if total > display_count else ""
        return f"{header}\n\n{body}{footer}"

    def _format_merchant_result(self, merchant_name: str, data: list) -> str:
        """格式化商人搜索结果（含作物名）"""
        total = len(data)
        for item in data:
            income, income_str = self._calc_item_income(item)
            item["_income"] = income
            item["_income_str"] = income_str
        data.sort(key=lambda x: x.get("_income", 0), reverse=True)
        display_count = min(total, 5)

        recall_hint = f" · {self.recall_seconds}s撤回" if self.recall_seconds > 0 else ""
        lines = [f"🏪 商人「{merchant_name}」· 收购分享{recall_hint}"]
        if data:
            lines.append("")
            lines.append("🏆 最高  📦xxx  💰xxx万")
        lines.append("")
        lines.append(f"共{total}条 | 按百工币↓")
        header = "\n".join(lines)

        items = []
        for i, item in enumerate(data[:display_count]):
            uid = str(item["uid"])[:12]
            mult = item["price_multiplier"]
            qty = item["quantity"]
            income_str = item.get("_income_str", "?")
            crop = item.get("crop_name", "?")

            rank = f"{i+1:>2}."
            items.append(
                f"{rank} 🌾{crop}  {income_str}万  ✨x{mult:.1f}  ×{qty}\n     UID {uid}"
            )

        body = "\n".join(items)
        footer = f"\n\n━━ 仅显示前{display_count}条" if total > display_count else ""
        return f"{header}\n\n{body}{footer}"

    def _format_ranch_result(self, name: str, data: list) -> str:
        total = len(data)

        # 计算百工币收入并排序
        for item in data:
            income, income_str = self._calc_item_income(item)
            item["_income"] = income
            item["_income_str"] = income_str
        data.sort(key=lambda x: x.get("_income", 0), reverse=True)
        display_count = min(total, 5)

        recall_hint = f" · {self.recall_seconds}s撤回" if self.recall_seconds > 0 else ""
        lines = [f"🐄 {name} · 牧场分享{recall_hint}"]
        if data:
            lines.append("")
            lines.append("🏆 最高  📦xxx  💰xxx万")
        lines.append("")
        lines.append(f"共{total}条 | 按百工币↓")
        header = "\n".join(lines)
        items = []
        for i, item in enumerate(data[:display_count]):
            uid = item["uid"][:12]
            mult = item["price_multiplier"]
            qty = item["quantity"]
            income_str = item.get("_income_str", "?")
            medals = ["🥇", "🥈", "🥉"]
            rank = medals[i] if i < 3 else f"  {i+1}."
            mult_tag = "🔥" if mult >= 2.0 else ("⭐" if mult >= 1.5 else "")
            mult_str = f"x{mult:.1f} {mult_tag}" if mult_tag else f"x{mult:.1f}  "
            items.append(
                f"{rank} 💰{income_str:>5}百工币  {mult_str:<6}  量{qty}\n\n      UID {uid}"
            )
        body = "\n\n".join(items)
        footer = f"\n\n━━ 仅显示前{display_count}条" if total > display_count else ""
        return f"{header}\n\n{body}{footer}"

    # ==================== 生命周期 & 轮询播报 ====================

    def _start_background_polling(self):
        """启动后台轮询任务"""
        try:
            loop = asyncio.get_running_loop()
            self._polling_task = loop.create_task(self._poll_loop())
            enabled_crops = "、".join(self.poll_crop_filter) if self.poll_crop_filter else "全部"
            logger.info(f"高价轮询播报已启动（每{self.poll_interval_minutes}分钟，监控作物：{enabled_crops}）")
        except RuntimeError:
            logger.warning("事件循环未运行，轮询将在首次请求时启动")

    async def _poll_loop(self):
        """后台轮询循环 — WebUI 开关+间隔控制，按群独立配置分发"""
        await asyncio.sleep(30)  # 启动后30秒再开始首次扫描
        while True:
            if self.polling_enabled:
                try:
                    # 先拉取一次源数据，给各群复用
                    source1_all = []
                    if self.enable_source1:
                        data = await self._fetch_source1_all("purchase")
                        if data:
                            source1_all = data
                    # 对每个白名单群生成独立播报
                    for gid in self.whitelist_groups:
                        # 检查该群是否启用播报
                        g_poll = self._get_group_setting(gid, "polling_enabled")
                        if g_poll is False:
                            continue  # 群显式关闭播报
                        msg = await self._poll_for_group(gid, source1_all, force=False)
                        if msg:
                            await self._broadcast_to_single_group(gid, msg)
                except Exception as e:
                    logger.error(f"轮询异常: {e}")
            await asyncio.sleep(self.poll_interval_minutes * 60)

    async def _poll_for_group(self, gid: str, source1_all: list, force: bool = False) -> Optional[str]:
        """为指定群生成独立播报（使用该群的作物列表和阈值，缺失则用全局）"""
        await self._ensure_unit_prices()

        # 该群监控的作物列表（独立>全局）
        g_crops = self._get_group_setting(gid, "poll_crops")
        if g_crops:
            crop_list = set(g_crops)
        else:
            crop_list = self.poll_crop_filter

        # 该群数据源开关（独立>全局）
        es1 = self._get_group_setting(gid, "enable_source1")
        if es1 is None:
            es1 = self.enable_source1
        es2 = self._get_group_setting(gid, "enable_source2")
        if es2 is None:
            es2 = self.enable_source2
        es3 = self._get_group_setting(gid, "enable_source3")
        if es3 is None:
            es3 = self.enable_source3

        all_2x: dict[str, list] = {}
        for crop_name in crop_list:
            seen = set()
            crop_items = []
            # 源1数据仅在传入且该群启用源1时使用
            if es1 and source1_all:
                for item in source1_all:
                    if item.get("crop_name") != crop_name:
                        continue
                    uid = str(item.get("uid", ""))
                    if uid not in seen:
                        seen.add(uid)
                        crop_items.append({
                            "uid": uid,
                            "price_multiplier": float(item.get("price_multiplier") or 0),
                            "quantity": int(item.get("quantity") or 0),
                            "merchant": item.get("merchant_name", "?"),
                            "source": SOURCE1_NAME,
                            "crop_name": crop_name,
                            "residence_level": int(item.get("residence_level") or 1),
                            "guild_maxed": bool(item.get("guild_maxed") or False),
                            "sale_price": int(item.get("sale_price") or 0),
                        })
            # 源2：HOK
            if es2:
                hok_items = await self._fetch_hok_items(crop_name)
                if hok_items:
                    for item in hok_items:
                        uid = str(item.get("uid", ""))
                        if uid in seen:
                            continue
                        if item.get("capped") or item.get("crop_name") != crop_name:
                            continue
                        seen.add(uid)
                        crop_items.append({
                            "uid": uid,
                            "price_multiplier": float(item.get("price_multiplier") or 0),
                            "quantity": int(item.get("quantity") or 0),
                            "merchant": item.get("merchant_name", "?"),
                            "source": SOURCE2_NAME,
                            "crop_name": crop_name,
                            "residence_level": int(item.get("residence_level") or 1),
                            "guild_maxed": bool(item.get("guild_maxed") or False),
                        })
            # 源3：家园站 — sold_out 或 markUsers非空 视为已达上限剔除
            if es3:
                try:
                    wsjj_items = await self._fetch_wsjj_items(crop_name)
                except Exception:
                    wsjj_items = None
                if wsjj_items:
                    for item in wsjj_items:
                        uid = str(item.get("uid", ""))
                        if uid in seen:
                            continue
                        if item.get("status") == "sold_out":
                            continue
                        if item.get("markUsers"):
                            continue
                        if item.get("cropName") != crop_name:
                            continue
                        seen.add(uid)
                        crop_items.append({
                            "uid": uid,
                            "price_multiplier": float(item.get("multiplier") or 0),
                            "quantity": int(item.get("quantity") or 0),
                            "merchant": item.get("merchantName", "?"),
                            "source": SOURCE3_NAME,
                            "crop_name": crop_name,
                            "residence_level": int(item.get("stallLevel") or 1),
                            "guild_maxed": item.get("baijiaMax") is True,
                        })
            if crop_items:
                crop_items.sort(key=lambda x: x["price_multiplier"], reverse=True)
                all_2x[crop_name] = crop_items

        if not all_2x:
            return None

        # 阈值过滤（独立>全局）
        g_thresholds = self._get_group_setting(gid, "poll_thresholds")
        thresholds = g_thresholds if g_thresholds else self._poll_thresholds
        filtered = {}
        for crop_name, items in all_2x.items():
            threshold = thresholds.get(crop_name, DEFAULT_POLL_THRESHOLDS.get(crop_name, 9_990_000))
            passed_with_income = []
            for item in items:
                income, _ = self._calc_item_income(item)
                if income >= threshold:
                    passed_with_income.append((income, item))
            if passed_with_income:
                passed_with_income.sort(key=lambda x: x[0], reverse=True)
                filtered[crop_name] = [item for _, item in passed_with_income[:5]]
        all_2x = filtered
        # 刷新历史最高价记录（取每种作物收入最高的一条）
        for crop_name, items in all_2x.items():
            if items:
                self._update_high_record(crop_name, items[0])
        if not all_2x:
            return None

        # 去重：使用每群独立已播报记录
        if not force:
            reported_key = f"_reported_2x_crops_{gid}"
            if not hasattr(self, reported_key):
                setattr(self, reported_key, set())
            reported = getattr(self, reported_key)
            new_crops = {c for c in all_2x if c not in reported}
            if not new_crops:
                return None
            if not (set(all_2x.keys()) & reported):
                reported.clear()
            reported.update(all_2x.keys())
            self._save_poll_state()
        return self._format_2x_broadcast(all_2x)

    async def _broadcast_to_single_group(self, gid: str, message: str):
        """向单个白名单群发送播报"""
        if not gid:
            return
        payload = []
        for chunk in message.split("\n"):
            if payload:
                payload.append({"type": "text", "data": {"text": "\n"}})
            payload.append({"type": "text", "data": {"text": chunk}})
        adapter = await self._find_broadcast_adapter()
        if not adapter:
            logger.warning(f"[居所] 广播到群{gid}: 未找到 adapter")
            return
        api = getattr(adapter, 'api', None)
        send_fn = getattr(api, 'send_group_msg', None) if api else None
        if not send_fn:
            send_fn = getattr(adapter, 'send_group_msg', None)
        if not send_fn:
            logger.warning(f"[居所] 广播到群{gid}: adapter 无 send_group_msg")
            return
        try:
            await send_fn(group_id=self._to_group_id(gid), message=payload)
            logger.info(f"[居所] 高价播报已发送到群{gid}")
        except Exception as e:
            logger.warning(f"[居所] 广播到群{gid} 失败: {e}")

    async def _do_poll_2x(self, force: bool = False) -> Optional[str]:
        """扫描勾选的作物在多源中的收购，百工币达阈值时返回格式化消息或None
        force=True 时跳过去重缓存，播报所有达阈值作物（手动"刷二"）
        注意：本方法返回全局过滤后的消息（用于"刷二"指令），后台轮询使用 _poll_per_group 各群独立"""
        await self._ensure_unit_prices()

        # 源1：一次拉取全部收购数据（后续按作物过滤）
        source1_all = []
        if self.enable_source1:
            data = await self._fetch_source1_all("purchase")
            if data:
                source1_all = data

        all_2x: dict[str, list] = {}

        for crop_name in self.poll_crop_filter:
            seen = set()
            crop_items = []

            # 源1：从全量数据中过滤该作物
            if source1_all:
                for item in source1_all:
                    if item.get("crop_name") != crop_name:
                        continue
                    uid = str(item.get("uid", ""))
                    if uid not in seen:
                        seen.add(uid)
                        crop_items.append({
                            "uid": uid,
                            "price_multiplier": float(item.get("price_multiplier") or 0),
                            "quantity": int(item.get("quantity") or 0),
                            "merchant": item.get("merchant_name", "?"),
                            "source": SOURCE1_NAME,
                            "crop_name": crop_name,
                            "residence_level": int(item.get("residence_level") or 1),
                            "guild_maxed": bool(item.get("guild_maxed") or False),
                            "sale_price": int(item.get("sale_price") or 0),
                        })

            # 源2：按作物查询
            if self.enable_source2:
                try:
                    data = await self._fetch_hok_items(crop_name)
                except Exception:
                    data = None
                if data:
                    for item in data:
                        if item.get("capped") or item.get("crop_name") != crop_name:
                            continue
                        uid = str(item.get("uid", ""))
                        if uid not in seen:
                            seen.add(uid)
                            crop_items.append({
                                "uid": uid,
                                "price_multiplier": float(item.get("price_multiplier") or 0),
                                "quantity": int(item.get("quantity") or 0),
                                "merchant": item.get("merchant", "?"),
                                "source": SOURCE2_NAME,
                                "crop_name": crop_name,
                                "residence_level": int(item.get("home_level") or 1),
                                "guild_maxed": item.get("home_max_level", "") == "是",
                            })

            # 源3：家园站 — sold_out 或 markUsers非空 视为已达上限剔除
            if self.enable_source3:
                try:
                    data = await self._fetch_wsjj_items(crop_name)
                except Exception:
                    data = None
                if data:
                    for item in data:
                        if item.get("status") == "sold_out":
                            continue
                        if item.get("markUsers"):
                            continue
                        if item.get("cropName") != crop_name:
                            continue
                        uid = str(item.get("uid", ""))
                        if uid not in seen:
                            seen.add(uid)
                            crop_items.append({
                                "uid": uid,
                                "price_multiplier": float(item.get("multiplier") or 0),
                                "quantity": int(item.get("quantity") or 0),
                                "merchant": item.get("merchantName", "?"),
                                "source": SOURCE3_NAME,
                                "crop_name": crop_name,
                                "residence_level": int(item.get("stallLevel") or 1),
                                "guild_maxed": item.get("baijiaMax") is True,
                            })

            if crop_items:
                crop_items.sort(key=lambda x: x["price_multiplier"], reverse=True)
                all_2x[crop_name] = crop_items

        if not all_2x:
            return None

        # 百工币阈值过滤（逐条判断）+ 每种作物取收入前5
        filtered = {}
        for crop_name, items in all_2x.items():
            threshold = self._poll_thresholds.get(crop_name, DEFAULT_POLL_THRESHOLDS.get(crop_name, 9_990_000))
            passed_with_income = []
            for item in items:
                income, _ = self._calc_item_income(item)
                if income >= threshold:
                    passed_with_income.append((income, item))
            if passed_with_income:
                passed_with_income.sort(key=lambda x: x[0], reverse=True)
                top5 = [item for _, item in passed_with_income[:5]]
                filtered[crop_name] = top5
                logger.debug(f"[居所] 作物'{crop_name}': {len(top5)}/{len(items)} 条达阈值{threshold}（取前5）")
            else:
                logger.debug(f"[居所] 作物'{crop_name}': 0/{len(items)} 条达阈值{threshold}，跳过播报")
        all_2x = filtered
        # 刷新历史最高价记录（取每种作物收入最高的一条）
        for crop_name, items in all_2x.items():
            if items:
                self._update_high_record(crop_name, items[0])
        if not all_2x:
            return None

        # 去重
        if not force:
            new_crops = {c for c in all_2x if c not in self._reported_2x_crops}
            if not new_crops:
                return None
            if not (set(all_2x.keys()) & self._reported_2x_crops):
                self._reported_2x_crops.clear()
            self._reported_2x_crops.update(all_2x.keys())
            self._save_poll_state()
        return self._format_2x_broadcast(all_2x)

    # ==================== 播报状态持久化（防重载重复播报） ====================

    def _load_poll_state(self):
        """从文件恢复已播报作物状态，避免插件重载后重复播报"""
        try:
            if os.path.exists(self._poll_state_file):
                with open(self._poll_state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 恢复全局已播报
                global_reported = data.get("global", [])
                self._reported_2x_crops = set(global_reported)
                # 恢复每群已播报
                for gid, crops in data.get("groups", {}).items():
                    setattr(self, f"_reported_2x_crops_{gid}", set(crops))
                logger.info(
                    f"[居所] 已恢复播报状态：全局{len(global_reported)}种，"
                    f"{len(data.get('groups', {}))}个群"
                )
        except Exception as e:
            logger.warning(f"[居所] 恢复播报状态失败: {e}")

    def _save_poll_state(self):
        """将已播报作物状态写入文件，使插件重载后不会重复播报"""
        try:
            data = {"global": sorted(self._reported_2x_crops), "groups": {}}
            for attr in dir(self):
                if attr.startswith("_reported_2x_crops_") and not attr.endswith("_"):
                    gid = attr[len("_reported_2x_crops_"):]
                    val = getattr(self, attr)
                    if isinstance(val, set) and gid:
                        data["groups"][gid] = sorted(val)
            with open(self._poll_state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[居所] 保存播报状态失败: {e}")
    def _load_high_records(self):
        """从文件恢复历史最高价记录（key=crop_name）"""
        try:
            if os.path.exists(self._high_records_file):
                with open(self._high_records_file, "r", encoding="utf-8") as f:
                    self._high_records = json.load(f) or {}
                logger.info(f"[居所] 已恢复历史最高价记录：{len(self._high_records)} 种作物")
        except Exception as e:
            logger.warning(f"[居所] 恢复历史最高价记录失败: {e}")
            self._high_records = {}
    def _save_high_records(self):
        """将历史最高价记录写入文件（持久化）"""
        try:
            with open(self._high_records_file, "w", encoding="utf-8") as f:
                json.dump(self._high_records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[居所] 保存历史最高价记录失败: {e}")
    def _update_high_record(self, crop_name: str, item: dict):
        """轮询到高价时更新该作物的历史最高记录（仅在收入更高时替换）"""
        income, income_str = self._calc_item_income(item)
        rec = self._high_records.get(crop_name)
        if rec is None or income > rec.get("income", 0):
            self._high_records[crop_name] = {
                "crop_name": crop_name,
                "uid": str(item.get("uid", "")),
                "quantity": int(item.get("quantity") or 0),
                "income": income,
                "income_str": income_str.replace("万", ""),
                "price_multiplier": float(item.get("price_multiplier") or 0),
                "source": item.get("source", "?"),
                "merchant": item.get("merchant", "?"),
                "ts": time.time(),
            }
            self._save_high_records()
            logger.info(f"[居所] 作物'{crop_name}'历史最高价刷新：💰{income_str}万 量{int(item.get('quantity') or 0)}")

    # ==================== 作物查询次数统计（持久化，自本版日期起） ====================

    def _resolve_data_dir(self) -> Path:
        """获取 AstrBot 规范的插件数据目录（独立于插件代码目录）。

        该目录位于 AstrBot 的 data 区内（data/plugin_data/<name>/），更新或重装
        插件时不会被清空，从而保证查询统计等运行时数据正确持久化。
        采用多层 fallback 兼容不同 AstrBot 版本/部署方式，任何一步失败都会回退，
        确保插件加载不会因路径 API 差异而崩溃。
        """
        # 1) 官方推荐（较新版本）：context.get_plugin_data_dir()
        try:
            ctx = getattr(self, "context", None)
            if ctx is not None:
                fn = getattr(ctx, "get_plugin_data_dir", None)
                if callable(fn):
                    p = fn()
                    if p:
                        pp = p if isinstance(p, Path) else Path(str(p))
                        pp.mkdir(parents=True, exist_ok=True)
                        return pp
        except Exception:
            pass
        # 2) StarTools.get_data_dir() -> data/plugin_data/<plugin_name>/
        try:
            from astrbot.api.star import StarTools
            p = StarTools.get_data_dir()
            if p:
                pp = p if isinstance(p, Path) else Path(str(p))
                pp.mkdir(parents=True, exist_ok=True)
                return pp
        except Exception:
            pass
        # 3) 底层路径工具：get_astrbot_data_path() / "plugin_data" / self.name
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            name = getattr(self, "name", None) or "jusuo"
            pp = Path(str(get_astrbot_data_path())) / "plugin_data" / name
            pp.mkdir(parents=True, exist_ok=True)
            return pp
        except Exception:
            pass
        # 4) 最后回退：插件目录（不推荐，但保证可用、不崩溃）
        return Path(os.path.dirname(os.path.abspath(__file__)))

    def _migrate_legacy_data(self, target_dir: Path):
        """若新数据目录尚无文件，但旧插件目录内有同名文件，则复制过来（兼容旧版部署）。"""
        try:
            import shutil
            legacy_dir = Path(os.path.dirname(os.path.abspath(__file__)))
            for fn in ("_crop_query_counts.json", "_high_records.json", "_poll_state.json"):
                src = legacy_dir / fn
                dst = target_dir / fn
                if src.exists() and not dst.exists():
                    shutil.copyfile(src, dst)
                    logger.info(f"[居所] 已迁移旧数据文件到规范目录：{fn}")
        except Exception as e:
            logger.warning(f"[居所] 迁移旧数据文件失败（可忽略）: {e}")

    def _load_crop_query_counts(self):
        """从文件恢复作物查询次数统计（日/周/总），兼容旧版扁平结构"""
        try:
            # 清理旧版查询历史文件（本版起改为次数统计）
            old = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_query_history.json")
            if os.path.exists(old):
                try:
                    os.remove(old)
                    logger.info("[居所] 已清理旧的查询历史文件")
                except Exception:
                    pass
            if os.path.exists(self._crop_query_counts_file):
                with open(self._crop_query_counts_file, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                # 旧版为扁平 dict[str,int]（仅 total），新版本为含 total/daily/weekly 的嵌套结构
                if data and all(isinstance(v, int) for v in data.values()):
                    self._crop_query_counts = {"total": data, "daily": {}, "weekly": {}}
                else:
                    self._crop_query_counts = {
                        "total": (data.get("total") or {}),
                        "daily": (data.get("daily") or {}),
                        "weekly": (data.get("weekly") or {}),
                    }
                logger.info(f"[居所] 已恢复作物查询次数统计：{len(self._crop_query_counts.get('total', {}))} 种（总）")
        except Exception as e:
            logger.warning(f"[居所] 恢复作物查询次数统计失败: {e}")
            self._crop_query_counts = {"total": {}, "daily": {}, "weekly": {}}

    def _save_crop_query_counts(self):
        """将作物查询次数统计写入文件（持久化）"""
        try:
            with open(self._crop_query_counts_file, "w", encoding="utf-8") as f:
                json.dump(self._crop_query_counts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[居所] 保存作物查询次数统计失败: {e}")

    # ==================== 「已录入数据」统计（跨三站按 uid 去重，7 天窗口累计） ====================
    def _load_录入_records(self):
        """从文件恢复「已录入数据」统计（每个 uid 被计入的 7 天周期列表）"""
        try:
            if os.path.exists(self._录入_file):
                with open(self._录入_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    uids = data.get("uids", {}) or {}
                    self._录入_records = {
                        "start_date": data.get("start_date") or self.version_date,
                        "last_compute": float(data.get("last_compute", 0.0) or 0.0),
                        "uids": uids if isinstance(uids, dict) else {},
                    }
                    n = sum(len(v) for v in self._录入_records["uids"].values())
                    logger.info(f"[居所] 已恢复「已录入数据」统计：{n} 条记录（{len(self._录入_records['uids'])} 个 uid）")
                    return
        except Exception as e:
            logger.warning(f"[居所] 加载已录入数据失败: {e}")
        self._录入_records = {"start_date": self.version_date, "last_compute": 0.0, "uids": {}}

    def _save_录入_records(self):
        """将「已录入数据」统计写入文件（持久化）"""
        try:
            with open(self._录入_file, "w", encoding="utf-8") as f:
                json.dump(self._录入_records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[居所] 保存已录入数据失败: {e}")

    def _录入_period(self, dt=None) -> int:
        """以统计起始日为锚点，每 7 天一个周期桶，返回周期序号（从 0 开始）"""
        from datetime import datetime as _dt
        if dt is None:
            dt = _dt.now()
        try:
            start = _dt.strptime(self._录入_records.get("start_date") or self.version_date, "%Y-%m-%d")
        except Exception:
            start = _dt.now()
        return max(0, (dt - start).days // 7)

    async def _compute_录入_data(self) -> int:
        """跨三站拉取所有作物条目 → 提取 uid → 跨站去重 → 按 7 天窗口累计记录数 → 持久化。返回累计记录数。

        统计范围：源1（居所站）全量作物收购 + 源2/源3 按 KNOWN_CROPS 逐作物遍历合并。
        去重：跨三站的 uid 统一小写比较；同一 uid 在每 7 天窗口内首次出现记 1 次，
        跨过 7 天窗口再次出现再记 1 次（累计记录数）。数据自 version_date 起计算，不补旧。
        """
        import asyncio as _asyncio
        import time as _time
        all_uids: set = set()
        # 源1：居所站全量作物收购（带 uid）
        try:
            items1 = await self._fetch_source1_all("purchase")
            if items1:
                for it in items1:
                    if not isinstance(it, dict):
                        continue
                    uid = str(it.get("uid", "") or "").strip()
                    if uid:
                        all_uids.add(uid)
        except Exception as e:
            logger.warning(f"[居所] 已录入数据·源1 拉取失败: {e}")
        # 源2/源3：按 KNOWN_CROPS 逐作物遍历合并去重
        sem = _asyncio.Semaphore(4)

        async def _gather_uids(fetcher, *args):
            async with sem:
                try:
                    items = await fetcher(*args)
                except Exception:
                    return set()
                if not isinstance(items, list):
                    return set()
                uids = set()
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    uid = str(it.get("uid", "") or "").strip()
                    if uid:
                        uids.add(uid)
                return uids

        tasks = []
        for crop in KNOWN_CROPS:
            if getattr(self, "enable_source2", True):
                tasks.append(_gather_uids(self._fetch_hok_items, crop))
            if getattr(self, "enable_source3", True):
                tasks.append(_gather_uids(self._fetch_wsjj_items, crop))
        if tasks:
            results = await _asyncio.gather(*tasks)
            for s in results:
                all_uids |= s
        # 按 7 天窗口累计
        period = self._录入_period()
        recs = self._录入_records
        uids_map = recs.setdefault("uids", {})
        new_total = 0
        for uid in all_uids:
            periods = uids_map.get(uid)
            if periods is None:
                uids_map[uid] = [period]
                new_total += 1
            elif period not in periods:
                periods.append(period)
                new_total += 1
        recs["last_compute"] = _time.time()
        self._save_录入_records()
        total = sum(len(v) for v in uids_map.values())
        logger.info(f"[居所] 已录入数据·本次新增 {new_total} 条，累计 {total} 条（{len(uids_map)} 个 uid，周期#{period}）")
        return total

    def _increment_crop_count(self, name: str):
        """作物被查询一次，日/周/总计数 +1 并持久化"""
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            iso = now.isocalendar()
            cur_week = f"{iso[0]}-W{iso[1]:02d}"
            t = self._crop_query_counts.setdefault("total", {})
            t[name] = int(t.get(name, 0)) + 1
            d = self._crop_query_counts.setdefault("daily", {}).setdefault(today, {})
            d[name] = int(d.get(name, 0)) + 1
            w = self._crop_query_counts.setdefault("weekly", {}).setdefault(cur_week, {})
            w[name] = int(w.get(name, 0)) + 1
            self._save_crop_query_counts()
        except Exception as e:
            logger.warning(f"[居所] 更新作物查询次数失败: {e}")

    def _format_2x_broadcast(self, all_2x: dict) -> str:
        """格式化高价播报消息"""
        lines = ["🔥 自动高价播报 · 达到阈值收购", "━━━━━━━━━━━━━━"]

        for crop_name, items in all_2x.items():
            lines.append(f"  🌾 {crop_name}")
            for item in items[:5]:
                mult = item["price_multiplier"]
                qty = item["quantity"]
                uid = str(item["uid"])[:12]
                # 计算百工币
                income, income_str = self._calc_item_income(item)
                lines.append(f"     💰{income_str:>5}百工币  ✨x{mult:.1f}  ×{qty}")
                lines.append(f"     UID {uid}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━")
        lines.append(f"📋 共 {sum(len(v) for v in all_2x.values())} 条达阈值收购 ")
        return "\n".join(lines)

    async def _broadcast_to_groups(self, message: str):
        """向白名单群广播播报 — adapter 直发"""
        if not self.whitelist_groups:
            logger.warning("[居所] 广播：未配置白名单群，仅日志输出播报内容")
            logger.info(f"高价播报（无白名单群）:\n{message}")
            return

        # 构建 text segment 数组
        payload = []
        for chunk in message.split("\n"):
            if payload:
                payload.append({"type": "text", "data": {"text": "\n"}})
            payload.append({"type": "text", "data": {"text": chunk}})

        adapter = await self._find_broadcast_adapter()
        if not adapter:
            logger.warning("[居所] 广播：未找到 adapter，仅日志输出播报内容")
            logger.info(f"高价播报（未找到广播通道）:\n{message}")
            return

        api = getattr(adapter, 'api', None)
        send_fn = getattr(api, 'send_group_msg', None) if api else None
        if not send_fn:
            send_fn = getattr(adapter, 'send_group_msg', None)
        if not send_fn:
            logger.warning("[居所] 广播：adapter 无 send_group_msg")
            return

        sent_count = 0
        for gid in self.whitelist_groups:
            try:
                await send_fn(group_id=self._to_group_id(gid), message=payload)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[居所] 广播：发送到群{gid} 失败: {e}")

        if sent_count > 0:
            logger.info(f"[居所] 高价播报已发送到 {sent_count} 个白名单群")
        else:
            logger.warning(f"[居所] 广播：所有白名单群发送失败")

    # ==================== 白名单 & 管理员工具方法 ====================

    def _is_self_message(self, event: AstrMessageEvent) -> bool:
        """检查消息是否来自机器人自身（含 Agent 生成的命令回显）"""
        sender = self._get_sender_qq(event)
        if not sender:
            return False
        msg = event.message_obj
        # 方法1：对比消息对象的 bot 自身 ID 属性
        for attr in ('self_id', 'bot_id', 'bot_qq', 'self_qq'):
            bot_id = str(getattr(msg, attr, '') or '')
            if bot_id and sender == bot_id:
                return True
            # 方法2：对比插件实例上缓存的 bot ID
            val = str(getattr(self, f'_{attr}', ''))
            if val and sender == val:
                return True
        return False

    def _is_agent_code_execution(self, event: AstrMessageEvent) -> bool:
        """检测是否为 Agent 直接执行的 Python 代码片段（astrbot_execute_python 回显）"""
        text = event.message_str or ""
        if not text:
            return False
        # Agent 生成的 Python 代码特征：包含 import + API 调用模式
        code_patterns = [
            "import aiohttp", "import asyncio", "import ssl",
            "async def main():", "asyncio.run(main())",
            "HOK_API = ", "ClientSession()",
        ]
        match_count = sum(1 for pat in code_patterns if pat in text)
        # 命中2个以上模式 → 确认为 agent 代码执行
        return match_count >= 2

    def _get_sender_qq(self, event: AstrMessageEvent) -> str:
        """从事件中提取发送者 QQ 号"""
        msg = event.message_obj
        for attr in ('sender_id', 'user_id', 'author_id', 'sender_qq', 'qq', 'uin'):
            val = getattr(msg, attr, None)
            if val:
                return str(val)
        try:
            uid = event.get_sender_id()
            if uid:
                return str(uid)
        except Exception:
            pass
        return ""

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """检查发送者是否为管理员"""
        if not self.admin_qqs:
            return False
        sender_qq = self._get_sender_qq(event)
        return sender_qq in self.admin_qqs

    def _get_group_setting(self, gid: str, key: str):
        """获取群的独立设置，未配置则返回 None（由调用方 fallback 到全局）"""
        if gid in self._group_settings and key in self._group_settings[gid]:
            return self._group_settings[gid][key]
        return None

    def _check_qq_rate_limit(self, event: AstrMessageEvent) -> Optional[str]:
        """检查QQ号查询频率限制，通过返回None，超限返回提示消息"""
        if self._is_admin(event):
            return None

        import time as _time
        sender_qq = self._get_sender_qq(event)
        if not sender_qq:
            return None  # 无法获取QQ号则放行

        now = _time.time()
        # 清理过期记录
        if sender_qq in self._qq_query_timestamps:
            self._qq_query_timestamps[sender_qq] = [
                t for t in self._qq_query_timestamps[sender_qq]
                if now - t < self._qq_rate_limit_window
            ]
            if not self._qq_query_timestamps[sender_qq]:
                del self._qq_query_timestamps[sender_qq]

        timestamps = self._qq_query_timestamps.get(sender_qq, [])
        if len(timestamps) >= self._qq_rate_limit_max:
            oldest = min(timestamps)
            remaining = int(self._qq_rate_limit_window - (now - oldest))
            minutes = remaining // 60
            seconds = remaining % 60
            wait_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
            return f"⏳ 查询过于频繁，请{wait_str}后再试（10分钟内限3次查询，管理员不受限）"

        # 记录本次查询
        if sender_qq not in self._qq_query_timestamps:
            self._qq_query_timestamps[sender_qq] = []
        self._qq_query_timestamps[sender_qq].append(now)
        return None

    def _get_group_id(self, event: AstrMessageEvent) -> str:
        """从事件中提取群/频道 ID"""
        msg = event.message_obj
        for attr in ('group_id', 'chat_id', 'channel_id', 'guild_id', 'session_id'):
            val = getattr(msg, attr, None)
            if val:
                return str(val)
        try:
            sid = event.get_session_id()
            if sid:
                return str(sid)
        except Exception:
            pass
        return ""

    @staticmethod
    def _to_group_id(gid: str):
        """QQ 平台 gid 为纯数字字符串需转 int；微信等平台 gid 非数字保留字符串"""
        try:
            return int(gid)
        except (ValueError, TypeError):
            return gid

    def _check_at_bot(self, event: AstrMessageEvent) -> bool:
        """检测消息是否 @了机器人"""
        msg = event.message_obj
        # 收集可能的 bot id
        bot_ids = set()
        for attr in ('self_id', 'bot_id', 'bot_qq', 'self_qq'):
            val = getattr(msg, attr, '') or getattr(self, f'_{attr}', '')
            if val:
                bot_ids.add(str(val))

        # 方法1: 消息对象自带标记
        for attr in ('is_at_me', 'is_at_bot', 'mentioned', 'is_at'):
            if getattr(msg, attr, False):
                return True

        # 方法2: at_list / ats 包含 bot 自身
        at_list = getattr(msg, 'at_list', []) or getattr(msg, 'ats', [])
        for bid in bot_ids:
            if bid in [str(a) for a in at_list]:
                return True

        # 方法3: 消息文本含 @bot名称 模式
        text = event.message_str or ""
        bot_name = getattr(msg, 'self_name', '') or getattr(msg, 'bot_name', '')
        if bot_name and f"@{bot_name}" in text:
            return True

        # 方法4: raw message / message chain 包含 CQ码 at bot
        raw = getattr(msg, 'raw_message', '') or getattr(msg, 'message', '') or ""
        if isinstance(raw, str) and "[CQ:at" in raw:
            for bid in bot_ids:
                if f"qq={bid}" in raw:
                    return True
            # 没匹配到具体ID但确实有 at，保守认为可能@了bot
            return True

        # 方法5: 检查 message_chain / segments 结构
        chain = getattr(msg, 'message', None) or getattr(msg, 'message_chain', None)
        if isinstance(chain, (list, tuple)):
            for seg in chain:
                if isinstance(seg, dict) and seg.get('type') == 'at':
                    target = str(seg.get('data', {}).get('qq', ''))
                    if target in bot_ids or target == 'all':
                        return True
                    return True  # 有 at 段即认为可能

        return False

    def _whitelist_auto_reply(self, gid: str = "") -> str:
        """白名单自动回复内容：群独立custom_reply > 全局custom_reply > 默认指南"""
        # 优先用群独立 custom_reply
        if gid:
            group_reply = self._get_group_setting(gid, "custom_reply")
            if group_reply is not None:
                if group_reply:
                    return group_reply
                # 群显式配置为空字符串 → 用全局或默认
                if self.custom_reply:
                    return self.custom_reply
                return self._default_reply_text()
            # 群未配置 custom_reply → 用全局
        if self.custom_reply:
            return self.custom_reply
        return self._default_reply_text()

    def _default_reply_text(self) -> str:
        """默认使用指南"""
        return textwrap.dedent(f"""
        🌾 王世杰居所助手

        💡 直接发作物名即可查询：
          炎霞辣椒 / 灿金云棉 / 旭日辣椒 / 星夜龙眼 / 蝶影莲子 等

        🔍 指令：高倍 <作物> · 搜索 <商人> · 牧场 <产品> · 家具 <家具>
           交友墙 · 模板 · 帮助 · 状态

        🔗 github.com/YDMY007/astrbot_plugin_jusuo
        """).strip()
    # ==================== 生命周期 & 轮询播报 ====================

    async def terminate(self):
        if self._polling_task:
            self._polling_task.cancel()
        # 恢复原始 plain_result
        if hasattr(self, '_snowluma_original_plain_result'):
            AstrMessageEvent.plain_result = self._snowluma_original_plain_result
            logger.info("[居所] SnowLuma 修复已卸载，plain_result 已恢复")
        logger.info("居所查询插件已卸载")
