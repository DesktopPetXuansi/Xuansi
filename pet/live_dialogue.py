"""只提交结束的话段，拒绝重复事件和已关闭麦克风的迟到结果。"""

import logging

from .turn_latency import TurnLatency

LOG = logging.getLogger(__name__)


class LiveDialogue:
    def __init__(self, runtime):
        self.runtime = runtime
        self.last_final = -1

    def reset(self):
        self.last_final = -1

    async def accept(self, mic_epoch, update, settings, position, *, screen=None):
        runtime = self.runtime
        if (mic_epoch != runtime.microphone_epoch or not runtime.listening
                or not update.final or not update.text or update.turn <= self.last_final):
            return
        self.last_final = update.turn
        LOG.info("用户话段结束，开始回复 chars=%d", len(update.text))
        if screen is not None and (screen.version != runtime.screen_version or screen.epoch != runtime.epoch + 1):
            if screen.epoch == runtime.epoch + 1 and (runtime.job is None or runtime.job.done()):
                runtime.state.emit(runtime.epoch, "本轮屏幕分享已取消。")
                runtime.finished.emit(runtime.epoch)
            return
        runtime.epoch += 1
        epoch = runtime.epoch
        kind = "voice-screen" if screen is not None else "voice-final"
        runtime.screen_epoch = epoch if screen is not None else None
        timing = TurnLatency(update.endpoint_at) if update.endpoint_at is not None else TurnLatency()
        timing.mark("recognized", update.recognized_at if update.endpoint_at is not None else None)
        await runtime._replace(epoch, settings, update.text, kind, position, None, None, screen=screen, timing=timing)
