"""私有 Python 的安装前入口；只用标准库，探测与正式部署有明确边界。"""

import argparse
import configparser
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pet.ai.assessment import assess, assess_base, preferred_backend
from pet.ai.catalog import MODELS
from pet.ai.device import probe_device
from pet.ai.install_plan import (
    InstallPlan,
    default_model_dir,
    load_plan,
    prepare_plan,
    resources_for,
    save_plan,
)

LOG = logging.getLogger(__name__)


def read_ini(path: Path):
    content = path.read_bytes()
    encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(content.decode(encoding))
    return parser


def write_ini(path: Path, sections):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_dict(sections)
    with path.open("w", encoding="utf-16") as stream:
        parser.write(stream)


def probe(args):
    args.output.mkdir(parents=True, exist_ok=True)
    report = probe_device(args.app_dir, args.model_dir)
    backend = preferred_backend(report)
    sections = {"device": {"backend": backend, "model_dir": str(args.model_dir)}}
    base = assess_base(report)
    sections["base"] = {"status": base.status, "selectable": str(int(base.selectable)),
                        "reason": "；".join(base.reasons)}
    results = {}
    for model_id in MODELS:
        result = assess(report, model_id, backend)
        results[model_id] = asdict(result)
        sections[model_id] = {"status": result.status, "selectable": str(int(result.selectable)),
                              "reason": "；".join(result.reasons)}
    write_ini(args.output / "device.ini", sections)
    (args.output / "device.json").write_text(json.dumps({"device": asdict(report), "assessments": results},
                                           ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def create_plan(args):
    values = read_ini(args.choices)["choices"]
    mode = values.get("mode", "local")
    model_id = values.get("model", "qwen3.5-9b")
    app_dir, model_dir = Path(values["app_dir"]), Path(values["model_dir"])
    report = probe_device(app_dir, model_dir)
    backend = values.get("backend", "auto")
    backup = ("qwen3.5-4b",) if values.getboolean("backup", False) and model_id != "qwen3.5-4b" else ()
    voice = tuple(item for item in ("asr", "tts", "realtime") if values.getboolean(item, False))
    plan = InstallPlan(mode=mode, primary_model_id=model_id, backup_model_ids=backup,
                       backend=backend, app_dir=str(app_dir), model_dir=str(model_dir), voice_components=voice,
                       policy="online_first" if mode == "api" else
                       "local_first" if values.getboolean("online", False) else "local_only")
    profile = None
    if args.profile:
        from pet.ai.settings import ModelProfile

        profile = ModelProfile.from_dict(json.loads(args.profile.read_text(encoding="utf-8-sig")))
    plan = prepare_plan(plan, report, profile)
    resources = resources_for(plan)
    save_plan(plan, args.output)
    summary = f"模式：{'在线 API' if mode == 'api' else MODELS[model_id].name}\r\n"
    summary += f"后端：{plan.backend if mode == 'local' else '不安装本地引擎'}\r\n模型/语音目录：{model_dir}\r\n"
    summary += f"下载合计：{plan.download_bytes / 2**20:.1f} MiB\r\n"
    summary += "资源：" + ("、".join(item.id for item in resources) or "无本地模型和语音资源")
    args.output.with_suffix(".txt").write_text(summary, encoding="utf-8", newline="")
    return 0


def apply_settings(args):
    """只更新安装时明确选择的字段，原配置损坏时拒绝静默覆盖。"""
    plan = load_plan(args.plan)
    path = Path(plan.app_dir) / "data/settings.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(raw, dict):
        raise ValueError("原配置损坏，保留文件并停止安装")
    previous_settings = json.dumps(raw, ensure_ascii=False, indent=2) if path.exists() else None
    ai = dict(raw.get("ai", {}))
    models = Path(plan.model_dir or default_model_dir())
    profile = None
    if args.profile or plan.policy != "local_only":
        # root 的配置模型校验真实证明绑定和端点格式，不接受任意未经验证的 profile。
        from pet.ai.settings import ModelProfile

        profile_raw = json.loads(args.profile.read_text(encoding="utf-8-sig")) if args.profile else ai.get("profile", {})
        profile = ModelProfile.from_dict(profile_raw)
        if not profile.is_verified("text", "image", "tools", "stream", "cancel"):
            raise ValueError("API 安装需要完整能力验证通过")
        ai["profile"] = asdict(profile)
    if plan.mode == "api" and profile is None:
        raise ValueError("缺少已验证的在线 API 配置，安装未完成")
    ai.update(schema_version=1, policy=plan.policy, local_model=plan.primary_model_id,
              local_backend=plan.backend, model_dir=str(models), voice_components=plan.voice_components)
    if plan.mode == "api":
        raw.update(model_path="", projector_path="")
    else:
        model = MODELS[plan.primary_model_id]
        raw.update(model_path=str(models / model.model_path), projector_path=str(models / model.projector_path),
                   gpu_layers=0 if plan.backend == "cpu" else 99)
    ai.update(backup_model_path="", backup_projector_path="")
    if plan.backup_model_ids:
        backup = MODELS[plan.backup_model_ids[0]]
        ai.update(backup_model_path=str(models / backup.model_path),
                  backup_projector_path=str(models / backup.projector_path))
    if "tts" not in plan.voice_components:
        raw.update(speak_replies=False, speak_observations=False)
    if "realtime" not in plan.voice_components:
        raw["realtime_voice"] = False
    elif "asr" not in plan.voice_components:
        # 单识别组件固定为可用模式，两者都有时才保留原来的用户选择。
        raw["realtime_voice"] = True
    raw["ai"] = ai
    path.parent.mkdir(parents=True, exist_ok=True)
    if previous_settings is not None:
        # 安装选择会更新模型/语音字段，旧自定义路径保留为独立恢复副本，不覆盖历次副本。
        backup = path.with_name(f'settings.before-install-{uuid4().hex}.json')
        backup.write_text(previous_settings, encoding='utf-8')
    # 配置必须最后提交；后续安装失败清理新凭据时，旧配置仍引用原凭据。
    save_plan(plan, path.with_name("install-plan.json"))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    LOG.info("安装选择已应用，未修改用户人设、记忆或其他配置")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("probe")
    command.add_argument("--app-dir", type=Path, required=True)
    command.add_argument("--model-dir", type=Path, default=Path(default_model_dir()))
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("presets")
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("profile")
    command.add_argument("--choices", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("plan")
    command.add_argument("--choices", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--profile", type=Path)
    for name in ("validate", "apply"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        if name == "apply":
            command.add_argument("--profile", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "presets":
            from pet.ai.provider_catalog import preset_profiles

            write_ini(args.output, {str(index): {key: str(value) for key, value in asdict(profile).items()
                                               if key in ("provider", "region", "endpoint", "model", "mode", "context_tokens")}
                                    for index, profile in enumerate(preset_profiles())})
            return 0
        if args.command == "profile":
            from pet.ai.settings import ModelProfile

            values = read_ini(args.choices)["profile"]
            profile = ModelProfile(provider=values["provider"], region=values["region"],
                                   endpoint=values["endpoint"], model=values["model"],
                                   mode=values.get("mode", "default"),
                                   context_tokens=values.getint("context_tokens", 65536),
                                   capabilities=("text", "image", "tools", "stream", "cancel")).validate()
            args.output.write_text(json.dumps(asdict(profile), ensure_ascii=False), encoding="utf-8")
            return 0
        if args.command == "probe":
            return probe(args)
        if args.command == "plan":
            return create_plan(args)
        if args.command == "apply":
            return apply_settings(args)
        plan = load_plan(args.plan)
        if not plan.app_dir or Path(plan.app_dir).resolve() != ROOT:
            raise ValueError("安装计划应用目录与当前部署目录不一致，请重新确认安装位置")
        LOG.info("安装计划已校验")
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        # 错误不拼接原始输入，避免被污染配置将秘密写入安装日志。
        LOG.error("安装前检查或计划应用失败，类别=%s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    raise SystemExit(main())
