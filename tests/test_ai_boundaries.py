"""用干净解释器证明共享规则与路由没有偷带桌面产品装配依赖。"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('standard_library_only,module', [
    (True, 'scripts.preflight'), (False, 'pet.ai.selection'),
])
def test_shared_modules_import_without_desktop_assembly(standard_library_only, module):
    # -S 禁用第三方 site-packages，实际检验安装前的标准库导入约束。
    flags = ['-I', '-S'] if standard_library_only else ['-I']
    code = (f'import importlib, sys; sys.path.insert(0, {str(ROOT)!r}); importlib.import_module({module!r}); '
            "assert not {'pet.config', 'pet.inference', 'pet.ai.assembly'} & sys.modules.keys(); "
            "assert not any(name.startswith('PySide6') for name in sys.modules)")
    result = subprocess.run([sys.executable, *flags, '-c', code], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
