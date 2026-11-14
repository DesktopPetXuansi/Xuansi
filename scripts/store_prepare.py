"""按已确认计划准备商店版资源；配置只在资源成功后提交，密钥不进入本入口。"""

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, fields
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pet.ai.install_plan import load_plan, save_plan
from pet.ai.settings import ModelProfile
from scripts.download_assets import deploy_plan
from scripts.preflight import apply_settings

LOG = logging.getLogger(__name__)


def validated_inputs(plan_path, profile_path=None):
    """读取所有输入而不创建目录；既有配置损坏时先停止，避免无效下载。"""
    value = os.environ.get("XUANSI_WRITABLE_ROOT", "")
    destination = Path(value)
    if not value or not destination.is_absolute():
        raise ValueError("商店准备需要明确的绝对可写根目录。")
    plan = load_plan(plan_path)
    if not plan.app_dir or Path(plan.app_dir).resolve() != destination.resolve():
        raise ValueError("安装计划与指定可写根目录不一致。")
    settings_path = destination / "data/settings.json"
    previous = json.loads(settings_path.read_text(encoding="utf-8-sig")) if settings_path.exists() else {}
    if not isinstance(previous, dict) or not isinstance(previous.get("ai", {}), dict):
        raise ValueError("既有设置结构无效，保留原文件并停止准备。")
    if plan.mode == "api" and plan.policy == "local_only":
        raise ValueError("在线安装计划必须包含在线策略。")
    profile = None
    if profile_path is not None or plan.policy != "local_only":
        raw = (json.loads(profile_path.read_text(encoding="utf-8-sig")) if profile_path is not None
               else previous.get("ai", {}).get("profile", {}))
        if not isinstance(raw, dict) or raw.keys() - {field.name for field in fields(ModelProfile)}:
            raise ValueError("档案只能包含已知配置与凭据引用。")
        profile = ModelProfile.from_dict(raw)
        if not profile.endpoint or not profile.model or not profile.is_verified("text", "image", "tools", "stream", "cancel"):
            raise ValueError("在线档案尚未完成能力验证。")
    if ((plan.provider_profile_id and (profile is None or plan.provider_profile_id != profile.fingerprint()))
            or (plan.credential_ref and (profile is None or plan.credential_ref != profile.credential_ref))):
        raise ValueError("安装计划与已验证档案不一致。")
    return destination, plan, profile


def prepare_install(plan_path, profile_path=None):
    destination, plan, profile = validated_inputs(plan_path, profile_path)
    # 无秘密快照固定本次选择；下载期间改动原计划或档案不会更换实际提交内容。
    token = uuid4().hex
    snapshot = destination / "data" / f".store-plan-{token}.json"
    profile_snapshot = snapshot.with_name(f".store-profile-{token}.json")
    try:
        save_plan(plan, snapshot)
        if profile is not None:
            profile_snapshot.write_text(json.dumps(asdict(profile), ensure_ascii=False), encoding="utf-8")
        LOG.info("商店资源准备开始，模式=%s", plan.mode)
        deploy_plan(plan)
        result = apply_settings(argparse.Namespace(plan=snapshot, profile=profile_snapshot if profile else None))
        LOG.info("商店资源及配置准备完成")
        return result
    finally:
        for path in (snapshot, snapshot.with_suffix(".tmp"), profile_snapshot):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                LOG.warning("准备快照清理未完成，类别=%s", type(exc).__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args(argv)
    try:
        return prepare_install(args.plan, args.profile)
    except Exception as exc:
        # CLI 边界不输出底层异常正文，避免损坏的输入将秘密带进日志。
        LOG.error("商店资源准备失败，类别=%s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    raise SystemExit(main())
