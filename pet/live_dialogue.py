"""只提交结束的话段，拒绝重复事件和已关闭麦克风的迟到结果。"""

import logging

LOG = logging.getLogger(__name__)


class LiveDialogue:
    def __init__(self, runtime):
        self.runtime = runtime
        self.last_final = -1

    def reset(self):
        self.last_final = -1

    async def accept(self, mic_epoch, update, settings, position):
        runtime = self.runtime
        if (mic_epoch != runtime.microphone_epoch or not runtime.listening
                or not update.final or not update.text or update.turn <= self.last_final):
            return
        self.last_final = update.turn
        runtime.epoch += 1
        LOG.info("用户话段结束，开始回复 chars=%d", len(update.text))
        await runtime._replace(runtime.epoch, settings, update.text, "voice-final", position, None, None)
