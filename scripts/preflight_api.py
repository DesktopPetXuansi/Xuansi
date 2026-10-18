"""安装前 API 合成验证入口；Key 只经短时环境或无回显标准输入进入内存。"""

import argparse
import asyncio
import getpass
import json
import logging
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pet.ai.credentials import CredentialStore, new_ref
from pet.ai.providers import ProviderError
from pet.ai.settings import ModelProfile
from pet.ai.validation import validate_profile

LOG = logging.getLogger(__name__)


def receipt_path(output):
    return output.with_suffix(output.suffix + '.credential-receipt')


def cleanup_profile(output: Path, *, store=None):
    """仅清理这个临时验证结果的独立新引用，不删除已有安装的凭据。"""
    receipt = receipt_path(output)
    if not receipt.is_file():
        return
    reference = receipt.read_text(encoding='utf-8').strip()
    profile = ModelProfile.from_dict(json.loads(output.read_text(encoding='utf-8')))
    if reference != profile.credential_ref:
        raise ValueError('临时凭据回执不一致，未执行清理。')
    (store or CredentialStore()).delete(reference)
    receipt.unlink()
    output.unlink()
    LOG.info('安装前验证临时凭据已清理')


async def validate_install_profile(draft: Path, output: Path, key: str, *, validator=None, store=None):
    if output.exists() or receipt_path(output).exists():
        raise ValueError('请先清理上一次安装前验证的临时结果，再重新验证。')
    profile = ModelProfile.from_dict(json.loads(draft.read_text(encoding='utf-8')))
    # 每次尝试都使用新引用；验证失败不会覆盖当前安装或先前已保存的Key。
    profile = replace(profile, credential_ref=new_ref(profile.endpoint), verified_capabilities=(),
                      verified_at='', verification_fingerprint='')
    store = store or CredentialStore()
    async with asyncio.timeout(180):
        verified = await (validator or validate_profile)(profile, key)
    if not verified.is_verified('text', 'image', 'tools', 'stream', 'cancel'):
        raise ValueError('安装前完整能力验证尚未通过。')
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + '.tmp')
        temporary.write_text(json.dumps(asdict(verified), ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(output)
        receipt_path(output).write_text(verified.credential_ref, encoding='utf-8')
        # 先留下无秘密恢复回执，再执行短Win32提交；硬超时也能回收本次新引用。
        # 该隔离CLI没有UI事件循环，短凭据操作同步完成以免取消早于后台线程落盘。
        store.write(verified.credential_ref, key)
    except BaseException:
        store.delete(verified.credential_ref)
        receipt_path(output).unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise
    LOG.info('安装前 API 验证结果已保存，不含密钥')
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cleanup', type=Path)
    args = parser.parse_args()
    try:
        if args.cleanup:
            cleanup_profile(args.cleanup)
            return 0
        if args.plan is None or args.output is None:
            parser.error('需要 --plan 与 --output')
        key = os.environ.pop('XUANSI_API_KEY_DRAFT', '')
        if not key and sys.stdin.isatty():
            key = getpass.getpass('API Key（不会显示或写入文件）：')
        if not key.strip():
            raise ValueError('请填写 API Key 后重新验证。')
        asyncio.run(validate_install_profile(args.plan, args.output, key))
        print(json.dumps({'ok': True, 'message': '文字、图片、工具、流式与本机取消验证已通过。'}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
        message = str(exc) if isinstance(exc, (ValueError, ProviderError)) else '验证失败，请检查网络、凭据和模型能力。'
        # 不输出异常回溯、HTTP请求对象、Key、正文或带授权头的地址。
        print(json.dumps({'ok': False, 'message': message}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
