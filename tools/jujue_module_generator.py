这个版本怎么样# -*- coding: utf-8 -*-
"""
三花聚顶 · 聚诀旗舰模块生成器（企业级优化版 · 完全版）
--------------------------------------------------
🌸 标准结构 / 多模板 / 安全校验 / 事件通知 / 国际化
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from string import Template
from typing import Dict, List, Optional, Tuple, Union

try:
    import aiofiles
    from aiofiles import os as aio_os
    ASYNC_SUPPORT = True
except ImportError:
    ASYNC_SUPPORT = False

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

# ==== 国际化支持 ====
class I18N:
    _translations = {
        "en": {
            "dir_created": "🌱 Directory created: {path}",
            "module_generated": "✅ Module generated: {path}",
            "qr_generated": "🌸 QR code generated: {path}",
            "event_notified": "📢 Event notified: {event}",
            "validation_passed": "✔️ Validation passed",
            "missing_required": "❌ Missing required fields: {fields}",
        },
        "zh": {
            "dir_created": "🌱 目录已创建: {path}",
            "module_generated": "✅ 模块生成成功: {path}",
            "qr_generated": "🌸 二维码已生成: {path}",
            "event_notified": "📢 已发送事件: {event}",
            "validation_passed": "✔️ 验证通过",
            "missing_required": "❌ 缺少必填字段: {fields}",
        }
    }

    @classmethod
    def t(cls, key: str, lang: str = "zh", **kwargs) -> str:
        return cls._translations.get(lang, {}).get(key, key).format(**kwargs)

# ==== 错误类型 ====
class JujueError(Exception):
    pass

class TemplateError(JujueError):
    pass

class ValidationError(JujueError):
    pass

class FileSystemError(JujueError):
    pass

# ==== 彩色日志 ====
class LogColor:
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

class EnhancedLogger:
    def __init__(self, name: str, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        formatter = logging.Formatter(
            f"{LogColor.BOLD}[%(asctime)s]{LogColor.ENDC} %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def color_log(self, msg: str, color: str = LogColor.OKGREEN):
        self.logger.info(f"{color}{msg}{LogColor.ENDC}")

    def error(self, msg: str, exc_info: Optional[Exception] = None):
        self.logger.error(f"{LogColor.FAIL}{msg}{LogColor.ENDC}", exc_info=exc_info)

    def warning(self, msg: str):
        self.logger.warning(f"{LogColor.WARNING}{msg}{LogColor.ENDC}")

# ==== 配置系统 ====
class TemplateSource(Enum):
    BUILTIN = auto()
    FILE = auto()
    REMOTE = auto()

@dataclass
class JujueConfig:
    AUTHOR: str = field(default="三花聚顶·聚诀生成器")
    MODULES_BASE: str = field(default="modules")
    LOG_LEVEL: int = field(default=logging.INFO)
    LANGUAGE: str = field(default="zh")
    TEMPLATE_SOURCE: TemplateSource = field(default=TemplateSource.BUILTIN)
    TEMPLATE_DIR: Optional[str] = field(default=None)
    TEMPLATE_REMOTE_URL: Optional[str] = field(default=None)
    MAX_FILENAME_LENGTH: int = field(default=64)
    BANNED_KEYWORDS: List[str] = field(default_factory=lambda: ["exec", "eval", "os.system", "subprocess"])
    GENERATE_TESTS: bool = field(default=True)
    GENERATE_QR: bool = field(default=True)
    VALIDATE_MODULE: bool = field(default=True)
    ALLOW_CREATE_BASE: bool = field(default=True)
    OVERWRITE_EXISTING: bool = field(default=False)

    def __post_init__(self):
        if self.TEMPLATE_SOURCE == TemplateSource.FILE and not self.TEMPLATE_DIR:
            raise ValueError("文件模板模式需要指定TEMPLATE_DIR")
        if self.TEMPLATE_SOURCE == TemplateSource.REMOTE and not self.TEMPLATE_REMOTE_URL:
            raise ValueError("远程模板模式需要指定TEMPLATE_REMOTE_URL")

    @classmethod
    def from_file(cls, config_path: str) -> 'JujueConfig':
        try:
            with open(config_path) as f:
                data = json.load(f)
                return cls(**data)
        except Exception as e:
            raise JujueError(f"配置加载失败: {str(e)}")

# ==== 模板管理 ====
class TemplateManager:
    def __init__(self, config: JujueConfig):
        self.config = config
        self.logger = EnhancedLogger("template")
        self._templates = self._load_builtin_templates()

    def _load_builtin_templates(self) -> Dict[str, Template]:
        return {
            "module": Template('''"""
${module_name} - 三花聚顶标准功能模块
生成时间: ${timestamp} | 作者: ${author}
描述: ${description}
"""
from core.core2_0.module.base import BaseModule
from core.core2_0.module.meta import ModuleMeta

class ${class_name}(BaseModule):
    """${module_name} 的业务实现"""

    def __init__(self, meta: ModuleMeta, context):
        super().__init__(meta, context)

    def preload(self):
        """预加载逻辑"""
        pass

    def setup(self):
        """初始化和依赖注册"""
        pass

    def start(self):
        """启动主业务"""
        pass

    def post_start(self):
        """启动后动作"""
        pass

    def stop(self):
        """停止和清理"""
        pass

    def on_shutdown(self):
        """系统关闭清理"""
        pass

    def handle_event(self, event_type: str, event_data: dict):
        """事件处理示例"""
        if event_type == "EXAMPLE_EVENT":
            # 实际业务逻辑
            pass
        return None
'''),
            "test": Template('''"""
${module_name} - 模块单元测试
"""
import pytest

def test_module_basic():
    """基础模块测试"""
    from modules.${dir_name}.module import ${class_name}
    m = ${class_name}(None, None)
    assert hasattr(m, "handle_event")
'''),
            "manifest": Template('''{
    "name": "${module_name}",
    "version": "${version}",
    "description": "${description}",
    "author": "${author}",
    "entry_points": ${entry_points},
    "dependencies": ${dependencies},
    "permissions": ${permissions},
    "config_schema": ${config_schema}
}''')
        }

    async def load_template(self, name: str) -> Template:
        if self.config.TEMPLATE_SOURCE == TemplateSource.BUILTIN:
            return self._get_builtin_template(name)
        elif self.config.TEMPLATE_SOURCE == TemplateSource.FILE:
            return await self._load_file_template(name)
        elif self.config.TEMPLATE_SOURCE == TemplateSource.REMOTE:
            # 可扩展为远程加载
            raise NotImplementedError("远程模板暂未实现")
        else:
            raise TemplateError(f"未知模板源: {self.config.TEMPLATE_SOURCE}")

    def _get_builtin_template(self, name: str) -> Template:
        if name not in self._templates:
            raise TemplateError(f"内置模板不存在: {name}")
        return self._templates[name]

    async def _load_file_template(self, name: str) -> Template:
        template_path = Path(self.config.TEMPLATE_DIR) / f"{name}.tmpl"
        try:
            async with aiofiles.open(template_path, "r", encoding="utf-8") as f:
                content = await f.read()
                return Template(content)
        except Exception as e:
            raise TemplateError(f"模板文件加载失败: {str(e)}")

# ==== 验证系统 ====
class ModuleValidator:
    def __init__(self, config: JujueConfig):
        self.config = config
        self.logger = EnhancedLogger("validator")

    async def validate_module(self, module_dir: Path) -> bool:
        required_files = ["module.py", "manifest.json"]
        if self.config.GENERATE_TESTS:
            required_files.append(f"test_{module_dir.name}.py")
        missing = []
        for fname in required_files:
            if not any(module_dir.glob(fname)):
                missing.append(fname)
        if missing:
            raise ValidationError(I18N.t("missing_required", self.config.LANGUAGE, fields=", ".join(missing)))
        try:
            manifest_path = module_dir / "manifest.json"
            async with aiofiles.open(manifest_path, "r") as f:
                manifest = json.loads(await f.read())
                if not isinstance(manifest, dict):
                    raise ValidationError("manifest.json 必须是JSON对象")
        except Exception as e:
            raise ValidationError(f"manifest验证失败: {str(e)}")
        self.logger.color_log(I18N.t("validation_passed", self.config.LANGUAGE), LogColor.OKGREEN)
        return True

    def validate_params(self, params: Dict) -> bool:
        required = ["module_name", "class_name", "dir_name"]
        missing = [field for field in required if field not in params]
        if missing:
            raise ValidationError(I18N.t("missing_required", self.config.LANGUAGE, fields=", ".join(missing)))
        for keyword in self.config.BANNED_KEYWORDS:
            if any(keyword in str(v).lower() for v in params.values()):
                raise ValidationError(f"参数包含禁止关键字: {keyword}")
        return True

# ==== 事件总线集成（可选） ====
def notify_event(event_type: str, payload: Dict):
    """尝试通过三花聚顶事件总线通知主控（如可用）"""
    try:
        from core.core2_0.event_bus import get_event_bus, is_event_bus_initialized
        if is_event_bus_initialized():
            event_bus = get_event_bus()
            event_bus.publish(event_type, payload)
            return True
    except Exception:
        pass
    return False

# ==== 生成引擎 ====
class JujueEngine:
    def __init__(self, config: JujueConfig):
        self.config = config
        self.logger = EnhancedLogger("engine", level=config.LOG_LEVEL)
        self.template_manager = TemplateManager(config)
        self.validator = ModuleValidator(config)

    async def generate_module(self, spec: Dict) -> Tuple[bool, Optional[Path]]:
        try:
            params = self._prepare_params(spec)
            self.validator.validate_params(params)
            module_dir = await self._prepare_directory(params["dir_name"])
            await self._generate_files(module_dir, params)
            if self.config.GENERATE_QR and HAS_QRCODE:
                await self._generate_qrcode(module_dir, params)
            if self.config.VALIDATE_MODULE:
                await self.validator.validate_module(module_dir)
            # 事件总线自动通知
            notified = notify_event("MODULE_GENERATED", {
                "name": params["module_name"],
                "author": params["author"],
                "path": str(module_dir)
            })
            if notified:
                self.logger.color_log(
                    I18N.t("event_notified", self.config.LANGUAGE, event="MODULE_GENERATED"),
                    LogColor.OKBLUE
                )
            self.logger.color_log(
                I18N.t("module_generated", self.config.LANGUAGE, path=module_dir),
                LogColor.OKGREEN
            )
            return True, module_dir
        except JujueError as e:
            self.logger.error(f"生成失败: {str(e)}", exc_info=e)
            return False, None
        except Exception as e:
            self.logger.error("未知错误发生", exc_info=e)
            return False, None

    def _prepare_params(self, spec: Dict) -> Dict:
        module_name = spec["name"]
        # ==== 自动补全 =====
        defaults = {
            "entry_points": json.dumps(spec.get("entry_points", ["cli", "api"])),
            "dependencies": json.dumps(spec.get("dependencies", [])),
            "permissions": json.dumps(spec.get("permissions", [])),
            "config_schema": json.dumps(spec.get("config_schema", {})),
        }
        params = {
            "module_name": module_name,
            "class_name": self._safe_classname(module_name),
            "dir_name": self._safe_filename(module_name),
            "author": spec.get("author", self.config.AUTHOR),
            "description": spec.get("description", ""),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": spec.get("version", "1.0.0"),
            **defaults
        }
        return params

    def _safe_classname(self, name: str) -> str:
        base = re.sub(r"[^\w-]", "", name).title().replace("_", "")
        return f"{base}Module"

    def _safe_filename(self, name: str) -> str:
        return re.sub(r"[^\w-]", "", name).lower().replace(" ", "_")[:self.config.MAX_FILENAME_LENGTH]

    async def _prepare_directory(self, dir_name: str) -> Path:
        module_dir = Path(self.config.MODULES_BASE) / dir_name
        if module_dir.exists():
            if not self.config.OVERWRITE_EXISTING:
                raise FileSystemError(f"目录已存在: {module_dir}")
            try:
                if ASYNC_SUPPORT:
                    await aio_os.rmdir(module_dir)
                else:
                    import shutil
                    shutil.rmtree(module_dir)
            except Exception as e:
                raise FileSystemError(f"目录清理失败: {str(e)}")
        try:
            module_dir.mkdir(parents=True, exist_ok=True)
            self.logger.color_log(
                I18N.t("dir_created", self.config.LANGUAGE, path=module_dir),
                LogColor.OKBLUE
            )
            return module_dir
        except Exception as e:
            raise FileSystemError(f"目录创建失败: {str(e)}")

    async def _generate_files(self, module_dir: Path, params: Dict) -> None:
        tasks = [
            self._generate_file(module_dir, "module.py", "module", params),
            self._generate_file(module_dir, "manifest.json", "manifest", params)
        ]
        if self.config.GENERATE_TESTS:
            tasks.append(
                self._generate_file(module_dir, f"test_{params['dir_name']}.py", "test", params)
            )
        await asyncio.gather(*tasks)

    async def _generate_file(self, dir_path: Path, filename: str, template_name: str, params: Dict) -> None:
        file_path = dir_path / filename
        try:
            template = await self.template_manager.load_template(template_name)
            content = template.safe_substitute(params)
            if ASYNC_SUPPORT:
                async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                    await f.write(content)
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception as e:
            raise FileSystemError(f"文件生成失败 {filename}: {str(e)}")

    async def _generate_qrcode(self, module_dir: Path, params: Dict) -> None:
        qr_path = module_dir / f"{params['dir_name']}.qr.png"
        try:
            qr = qrcode.make(f"module://{params['dir_name']}")
            qr.save(qr_path)
            self.logger.color_log(
                I18N.t("qr_generated", self.config.LANGUAGE, path=qr_path),
                LogColor.OKBLUE
            )
        except Exception as e:
            self.logger.error(f"QR码生成失败: {str(e)}")

# ==== CLI 入口 ====
async def async_main():
    parser = argparse.ArgumentParser(
        description="三花聚顶 · 聚诀旗舰模块生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python jujue.py --name ocr --desc "图片识别功能"
  python jujue.py --config config.json"""
    )
    parser.add_argument("--name", help="模块名称（如 ocr）")
    parser.add_argument("--desc", help="模块描述")
    parser.add_argument("--author", help="作者名称")
    parser.add_argument("--version", help="模块版本", default="1.0.0")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--lang", choices=["zh", "en"], default="zh", help="界面语言")
    parser.add_argument("--no-tests", action="store_true", help="不生成测试文件")
    parser.add_argument("--no-qr", action="store_true", help="不生成QR码")
    parser.add_argument("--no-validate", action="store_true", help="跳过验证")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    try:
        if args.config:
            config = JujueConfig.from_file(args.config)
        else:
            if not args.name:
                parser.error("必须指定--name或--config")
            config = JujueConfig(
                LANGUAGE=args.lang,
                LOG_LEVEL=logging.DEBUG if args.debug else logging.INFO,
                GENERATE_TESTS=not args.no_tests,
                GENERATE_QR=not args.no_qr,
                VALIDATE_MODULE=not args.no_validate
            )
    except Exception as e:
        print(f"{LogColor.FAIL}配置初始化失败: {str(e)}{LogColor.ENDC}")
        return

    spec = {
        "name": args.name,
        "description": args.desc or f"{args.name} 功能模块",
        "author": args.author or config.AUTHOR,
        "version": args.version
    }

    engine = JujueEngine(config)
    success, module_dir = await engine.generate_module(spec)
    if not success:
        print(f"{LogColor.FAIL}❌ 模块生成失败{LogColor.ENDC}")
        sys.exit(1)

if __name__ == "__main__":
    if not ASYNC_SUPPORT:
        print(f"{LogColor.WARNING}⚠️ 未检测到异步支持，将使用同步模式{LogColor.ENDC}")
    try:
        if ASYNC_SUPPORT:
            asyncio.run(async_main())
        else:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(async_main())
    except KeyboardInterrupt:
        print(f"\n{LogColor.WARNING}🚧 操作已取消{LogColor.ENDC}")
        sys.exit(1)
    except Exception as e:
        print(f"{LogColor.FAIL}💥 未处理的错误: {str(e)}{LogColor.ENDC}")
        sys.exit(1)
