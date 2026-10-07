"""Live2D 一次性眨眼与抬手时序；只公布已经验收的动作能力。"""

import logging
import time

# 保留原 pet.avatar 日志来源，迁移不改变筛选和诊断语义。
LOG = logging.getLogger("pet.avatar")

BLINK_CLOSE_SECONDS = 0.075


BLINK_HOLD_SECONDS = 0.025


BLINK_OPEN_SECONDS = 0.12


ARM_RAISE_VALUE = 30.0


ARM_RAISE_SECONDS = 0.45


ARM_HOLD_SECONDS = 0.7


# 只有在 CMO3 中建立并验收原生手臂关键形后才启用这项能力。
ARM_RAISE_BINDING_VERIFIED = False


def _smoothstep(value):
    """动作关键阶段使用平滑插值，避免眨眼和抬手突然跳变。"""
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


class AvatarMotion:
    """Live2D 一次性眨眼与抬手时序；只公布已经验收的动作能力。"""

    def _init_motion_state(self):
        """一次性动作与能力通知继续由同一个角色窗口持有。"""
        self._motion_capabilities = ()
        self._motion_name = None
        self._motion_started = None

    @property
    def available_motions(self):
        """仅向模型公布当前默认 Live2D 中已验证的原生动作。"""
        if not self._live2d_active or self._live2d_model is None:
            return ()
        actions = []
        if {"ParamEyeLOpen", "ParamEyeROpen"}.issubset(self._live2d_parameter_ids):
            actions.append("blink")
        if ARM_RAISE_BINDING_VERIFIED and "ParamArmRA" in self._live2d_parameter_ids:
            actions.append("raise_hand")
        return tuple(actions)

    def play_motion(self, motion):
        """在现有 Live2D 绘制帧上启动一次白名单动作。"""
        if motion not in self.available_motions:
            LOG.warning("忽略未绑定的玄司动作 action=%s", motion)
            return False
        self.cancel_motion()
        self._motion_name = motion
        self._motion_started = time.monotonic()
        if motion == "blink":
            self._live2d_model.SetAutoBlinkEnable(False)
        LOG.info("玄司动作开始 action=%s", motion)
        self.update()
        return True

    def cancel_motion(self):
        """取消动作并把参数恢复到中立值；休眠时继续保持闭眼。"""
        motion, self._motion_name = self._motion_name, None
        self._motion_started = None
        if motion is None:
            return False
        model = self._live2d_model
        if model is not None:
            if motion == "blink":
                if self.animation != "sleep":
                    model.SetParameterValue("ParamEyeLOpen", 1.0)
                    model.SetParameterValue("ParamEyeROpen", 1.0)
                model.SetAutoBlinkEnable(self.animation != "sleep")
            elif motion == "raise_hand" and "ParamArmRA" in self._live2d_parameter_ids:
                model.SetParameterValue("ParamArmRA", 0.0)
        LOG.info("玄司动作已中断 action=%s", motion)
        self.update()
        return True

    def _motion_parameter_values(self, now):
        """按单调时钟推进一次性动作；返回值由本帧 Live2D 参数写入。"""
        if self._motion_name is None or self._motion_started is None:
            return {}
        elapsed = max(0.0, now - self._motion_started)
        if self._motion_name == "blink":
            close_end = BLINK_CLOSE_SECONDS
            hold_end = close_end + BLINK_HOLD_SECONDS
            finish = hold_end + BLINK_OPEN_SECONDS
            if elapsed >= finish:
                self._motion_name = None
                self._motion_started = None
                self._live2d_model.SetAutoBlinkEnable(self.animation != "sleep")
                LOG.info("玄司动作结束 action=blink")
                eye_open = 1.0
            elif elapsed < close_end:
                eye_open = 1.0 - _smoothstep(elapsed / close_end)
            elif elapsed < hold_end:
                eye_open = 0.0
            else:
                eye_open = _smoothstep((elapsed - hold_end) / BLINK_OPEN_SECONDS)
            return {"ParamEyeLOpen": eye_open, "ParamEyeROpen": eye_open}

        if self._motion_name == "raise_hand":
            lower_start = ARM_RAISE_SECONDS + ARM_HOLD_SECONDS
            finish = lower_start + ARM_RAISE_SECONDS
            if elapsed >= finish:
                self._motion_name = None
                self._motion_started = None
                LOG.info("玄司动作结束 action=raise_hand")
                arm_value = 0.0
            elif elapsed < ARM_RAISE_SECONDS:
                arm_value = ARM_RAISE_VALUE * _smoothstep(elapsed / ARM_RAISE_SECONDS)
            elif elapsed < lower_start:
                arm_value = ARM_RAISE_VALUE
            else:
                arm_value = ARM_RAISE_VALUE * (1.0 - _smoothstep((elapsed - lower_start) / ARM_RAISE_SECONDS))
            return {"ParamArmRA": arm_value}
        return {}

    def _refresh_motion_capabilities(self):
        actions = self.available_motions
        if actions == self._motion_capabilities:
            return
        self._motion_capabilities = actions
        self.motion_capabilities_changed.emit(actions)
        LOG.info("玄司原生动作能力已更新 actions=%s", ",".join(actions) or "无")
