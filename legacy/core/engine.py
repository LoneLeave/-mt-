from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path

import numpy as np
import yaml

from .vision import Matcher, imwrite_unicode


class TaskError(RuntimeError):
    pass


class BreakLoop(Exception):
    pass


_PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*)\}")


class Runner:
    def __init__(
        self,
        device,
        matcher: Matcher,
        config: dict,
        templates_dir: Path,
        logs_dir: Path,
        dry_run: bool = False,
        max_minutes: float | None = None,
    ):
        self.device = device
        self.matcher = matcher
        self.config = config
        vision_cfg = config.get("vision") or {}
        runtime_cfg = config.get("runtime") or {}

        self.poll = float(vision_cfg.get("poll_interval", 0.4))
        self.default_timeout = float(vision_cfg.get("timeout", 20))
        self.tap_delay = float(runtime_cfg.get("tap_delay", 0.35))
        self.jitter = float(runtime_cfg.get("jitter", 0.15))
        self.loop_max_minutes = float(runtime_cfg.get("loop_max_minutes", 60))
        self.max_minutes = max_minutes
        self.save_on_error = bool(runtime_cfg.get("screenshot_on_error", True))

        self.templates_dir = Path(templates_dir)
        self.logs_dir = Path(logs_dir)
        self.dry_run = dry_run
        self.logger = logging.getLogger("auto")
        self.last_shot: np.ndarray | None = None
        self.task_dir = Path.cwd()
        self.started_at = time.time()

    # ---------- 对外 ----------
    def run_task(self, path: str | Path, extra_vars: dict | None = None) -> None:
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.task_dir = path.parent
        variables = dict(data.get("vars") or {})
        if extra_vars:
            variables.update(extra_vars)

        title = data.get("name") or path.stem
        self.logger.info("任务开始: %s", title)
        started = time.time()
        try:
            self.run_steps(data.get("steps") or [], variables)
        except BreakLoop:
            self.logger.info("任务在循环中被 break 结束")
        except Exception:
            if self.save_on_error:
                self._save_shot(f"fail_{path.stem}")
            raise
        finally:
            self.logger.info("任务结束: %s（耗时 %.1fs）", title, time.time() - started)

    def run_steps(self, steps: list, variables: dict) -> None:
        if not isinstance(steps, list):
            raise TaskError("steps 必须是列表")
        for step in steps:
            self._run_step(step, variables)

    # ---------- 内部 ----------
    def _run_step(self, step: dict, variables: dict) -> None:
        if not isinstance(step, dict):
            raise TaskError(f"步骤格式错误: {step!r}")
        action = step.get("action")
        if not action:
            raise TaskError(f"步骤缺少 action: {step}")
        handler = getattr(self, f"act_{action}", None)
        if handler is None:
            raise TaskError(f"未知 action: {action}")
        label = step.get("template") or step.get("name") or step.get("message") or ""
        self.logger.info("→ %s %s", action, label)
        handler(step, variables)

    def render(self, value, variables: dict):
        if isinstance(value, str):
            return _PLACEHOLDER.sub(lambda m: str(variables.get(m.group(1), m.group(0))), value)
        if isinstance(value, list):
            return [self.render(v, variables) for v in value]
        if isinstance(value, dict):
            return {k: self.render(v, variables) for k, v in value.items()}
        return value

    def tpl_path(self, name: str) -> Path:
        return self.matcher.resolve(name)

    def sleep(self, seconds: float) -> None:
        seconds = float(seconds)
        if seconds <= 0:
            return
        if self.jitter:
            seconds *= random.uniform(1.0 - self.jitter, 1.0 + self.jitter)
        time.sleep(seconds)

    def _grab(self) -> np.ndarray:
        shot = self.device.screencap()
        self.last_shot = shot
        return shot

    def wait_for(self, names: list[str], step: dict, variables: dict):
        names = [self.render(n, variables) for n in names]
        timeout = step.get("timeout", None)
        timeout = self.default_timeout if timeout is None else float(timeout)
        threshold = step.get("threshold")
        region = step.get("region")
        deadline = time.time() + timeout

        while True:
            shot = self._grab()
            for name in names:
                match = self.matcher.find(shot, self.tpl_path(name), threshold=threshold, region=region)
                if match is not None:
                    match.name = name
                    return match
            if time.time() >= deadline:
                return None
            time.sleep(self.poll)

    def _tap_match(self, match, step: dict, variables: dict) -> None:
        offset = step.get("offset") or [0, 0]
        x = match.center[0] + int(offset[0])
        y = match.center[1] + int(offset[1])
        long_press = int(step.get("long_press_ms") or 0)
        if self.dry_run:
            self.logger.info("[dry-run] 不点击 %s (%d,%d)", match.name, x, y)
        else:
            if long_press > 0:
                self.device.swipe(x, y, x, y, long_press)
            else:
                self.device.tap(x, y)
            self.logger.info("点击 %s @ (%d,%d) score=%.3f scale=%.3f", match.name, x, y, match.score, match.scale)
        self.sleep(step.get("tap_delay", self.tap_delay))

    def _screen_size(self) -> tuple[int, int]:
        if self.last_shot is not None:
            h, w = self.last_shot.shape[:2]
            return w, h
        return self.device.size()

    def _coord(self, x, y) -> tuple[int, int]:
        w, h = self._screen_size()
        x = int(x * w) if isinstance(x, float) else int(x)
        y = int(y * h) if isinstance(y, float) else int(y)
        return x, y

    def _save_shot(self, name: str) -> Path:
        shot = self.last_shot
        if shot is None:
            try:
                shot = self._grab()
            except Exception:
                raise
        path = self.logs_dir / "shots" / f"{name}.png"
        imwrite_unicode(path, shot)
        self.logger.info("截图已保存: %s", path)
        return path

    # ---------- actions ----------
    def act_launch(self, step: dict, variables: dict) -> None:
        package = self.render(step.get("package") or (self.config.get("device") or {}).get("package", ""), variables)
        if not package:
            raise TaskError("launch 缺少 package")
        if self.dry_run:
            self.logger.info("[dry-run] 启动 %s", package)
        else:
            self.device.launch(package)
        self.sleep(step.get("wait", 5))

    def act_stop(self, step: dict, variables: dict) -> None:
        package = self.render(step.get("package") or (self.config.get("device") or {}).get("package", ""), variables)
        self.device.force_stop(package)

    def act_sleep(self, step: dict, variables: dict) -> None:
        seconds = step.get("seconds", 1)
        if isinstance(seconds, list):
            seconds = random.uniform(float(seconds[0]), float(seconds[1]))
        self.sleep(seconds)

    def act_wait_template(self, step: dict, variables: dict) -> None:
        match = self.wait_for([step["template"]], step, variables)
        if match is None:
            raise TaskError(f"等待模板超时: {step['template']}")
        self.logger.info("已出现: %s score=%.3f", match.name, match.score)

    def act_wait_any(self, step: dict, variables: dict) -> None:
        match = self.wait_for(step["templates"], step, variables)
        if match is None:
            if step.get("required", True):
                raise TaskError(f"等待任一模板超时: {step['templates']}")
            return
        self.logger.info("命中: %s score=%.3f", match.name, match.score)
        if step.get("save_as"):
            variables[step["save_as"]] = Path(match.name).stem

    def act_click_template(self, step: dict, variables: dict) -> None:
        match = self.wait_for([step["template"]], step, variables)
        if match is None:
            if step.get("required", True):
                raise TaskError(f"没找到模板: {step['template']}")
            self.logger.info("未找到（可选，跳过）: %s", step["template"])
            return
        self._tap_match(match, step, variables)

    def act_click_any(self, step: dict, variables: dict) -> None:
        match = self.wait_for(step["templates"], step, variables)
        if match is None:
            if step.get("required", True):
                raise TaskError(f"没找到任一模板: {step['templates']}")
            return
        self._tap_match(match, step, variables)

    def act_assert_template(self, step: dict, variables: dict) -> None:
        if self.wait_for([step["template"]], step, variables) is None:
            raise TaskError(f"断言失败，界面没有: {step['template']}")

    def act_break_if_template(self, step: dict, variables: dict) -> None:
        self._break_check([step["template"]], step, variables)

    def act_break_if_any(self, step: dict, variables: dict) -> None:
        self._break_check(step["templates"], step, variables)

    def _break_check(self, names: list[str], step: dict, variables: dict) -> None:
        local = dict(step)
        local.setdefault("timeout", 0)
        if self.wait_for(names, local, variables) is not None:
            raise BreakLoop()

    def act_click_xy(self, step: dict, variables: dict) -> None:
        x, y = self._coord(step["x"], step["y"])
        if self.dry_run:
            self.logger.info("[dry-run] 不点击 (%d,%d)", x, y)
        else:
            self.device.tap(x, y)
        self.sleep(step.get("tap_delay", self.tap_delay))

    def act_swipe(self, step: dict, variables: dict) -> None:
        x1, y1 = self._coord(*step["from"])
        x2, y2 = self._coord(*step["to"])
        duration = int(step.get("duration_ms", 300))
        times = int(step.get("times", 1))
        for _ in range(times):
            if not self.dry_run:
                self.device.swipe(x1, y1, x2, y2, duration)
            self.sleep(step.get("interval", 0.3))

    def act_back(self, step: dict, variables: dict) -> None:
        if not self.dry_run:
            self.device.back()
        self.sleep(step.get("delay", 0.5))

    def act_keyevent(self, step: dict, variables: dict) -> None:
        if not self.dry_run:
            self.device.keyevent(step["key"])
        self.sleep(step.get("delay", 0.3))

    def act_screenshot(self, step: dict, variables: dict) -> None:
        name = step.get("name") or f"shot_{int(time.time())}"
        name = re.sub(r"[^\w\-]+", "_", self.render(name, variables))
        self._save_shot(name)

    def act_log(self, step: dict, variables: dict) -> None:
        self.logger.info("%s", self.render(step.get("message", ""), variables))

    def act_set(self, step: dict, variables: dict) -> None:
        for key, value in (step.get("vars") or {}).items():
            variables[key] = self.render(value, variables)

    def act_call(self, step: dict, variables: dict) -> None:
        path = Path(self.render(step["task"], variables))
        if not path.is_absolute():
            path = self.task_dir / path
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        merged = dict(data.get("vars") or {})
        merged.update(variables)
        merged.update(step.get("vars") or {})
        self.run_steps(data.get("steps") or [], merged)

    def act_loop(self, step: dict, variables: dict) -> None:
        times = int(step.get("times", 1))
        minutes = step.get("max_minutes", self.loop_max_minutes)
        minutes = float(minutes) if minutes is not None else 0.0
        if self.max_minutes:
            minutes = min(minutes, self.max_minutes) if minutes else self.max_minutes
        started = time.time()
        iterations = 0
        while True:
            if times and iterations >= times:
                break
            if minutes and (time.time() - started) / 60.0 >= minutes:
                self.logger.info("循环达到 %.0f 分钟上限，退出", minutes)
                break
            try:
                self.run_steps(step.get("steps") or [], variables)
            except BreakLoop:
                self.logger.info("命中退出条件，跳出循环")
                break
            iterations += 1
            self.sleep(step.get("interval", 0))
