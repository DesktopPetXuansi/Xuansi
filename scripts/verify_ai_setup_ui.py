"""原生模型设置页布局验收；仅合成配置，不读取Key、不联网、不启动模型或麦克风。"""

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet.ai.settings import AISettings, ModelProfile
from pet.config import Settings
from pet.panel import Panel

LOG = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    profile = ModelProfile(endpoint='https://api.example.com/v1', model='待配置',
                           capabilities=('text', 'image', 'tools', 'stream', 'cancel'))
    settings = replace(Settings(), model_path='C:/Models/qwen3.5-9b/model.gguf',
                       projector_path='C:/Models/qwen3.5-9b/mmproj.gguf',
                       ai=AISettings(policy='online_first', model_dir='C:/Models', profile=profile))
    panel = Panel(settings)
    panel.footer.set_provider('在线 · 合成服务 · 在线记忆检索未启用')
    page = panel.sections['model']
    samples = []
    try:
        panel.open_section('model')
        for width, height in ((880, 760), (520, 480)):
            panel.resize(width, height)
            application.processEvents()
            for anchor, widget in (('strategy', panel.model_page.ai_page.policy),
                                   ('api', panel.model_page.ai_page.key),
                                   ('privacy', panel.model_page.ai_page.cloud_memory)):
                page.ensureWidgetVisible(widget)
                QTest.qWait(120)
                filename = f'model-{anchor}-{width}x{height}.png'
                assert panel.grab().save(str(args.output / filename))
                sample = {'size': [panel.width(), panel.height()], 'anchor': anchor,
                          'horizontal_scroll_max': page.horizontalScrollBar().maximum(),
                          'vertical_scroll_max': page.verticalScrollBar().maximum(), 'file': filename}
                assert sample['size'] == [width, height] and sample['horizontal_scroll_max'] == 0, sample
                samples.append(sample)
        panel.footer.set_activity('官网资源上传 · 35%')
        panel.footer.setText('可用内存 8.0 GB · 麦克风关闭')
        assert '在线 · 合成服务' in panel.footer.text() and '35%' in panel.footer.text()
        report = {'passed': True, 'platform': application.platformName(), 'samples': samples,
                  'persistent_provider_during_upload_and_poll': True,
                  'scope': '真实Qt模型页；合成配置，无网络、凭据、音频及语言模型调用。'}
        (args.output / 'layout-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                      encoding='utf-8')
        LOG.info('模型设置原生布局验收完成 samples=%d', len(samples))
        print(json.dumps({'passed': True, 'samples': len(samples)}, ensure_ascii=False))
    finally:
        panel.hide()
        panel.deleteLater()
        application.processEvents()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
