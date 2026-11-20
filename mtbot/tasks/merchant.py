"""公会商人（2026-11-03 实机 720×1280 重写，替换「议价 >1100 才买」的错误模型）。

用户规则：**先点「议价」，确认折扣数字 ≤ -100（例如 -151），再点「购买」**。

页面：
- 商人手里的木牌角标显示折扣，形如「-151」（负号是折扣幅度，越大越便宜）。
- 底部大按钮默认是「议价」；选中商品后变成「💎-N」（购买）。
- 「当前累计 44/59人 议价 646」是公会累计值，**不是**购买阈值——旧代码拿它
  跟 1100 比，属于读错了区域和语义。
"""
from __future__ import annotations

import time
from pathlib import Path

from .. import layout as L
from .. import log
from ..pages import MainCity, MerchantPage
from .base import BaseTask, TaskContext, TaskResult

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "artifacts" / "verify" / "08"


class MerchantTask(BaseTask):
    name = "merchant"
    title = "公会商人"
    category = "reward"

    def run(self, ctx: TaskContext) -> TaskResult:
        ui, p = ctx.ui, self.p
        need = abs(int(p.get("min_discount", 100)))     # 折扣绝对值阈值：≥100 即「-100 以下」
        max_bargains = int(p.get("max_bargains", 20))   # 负值越大越赚 → 尽量压到界面上限
        timeout = float(p.get("timeout_sec", 180))
        cancel_only = bool(p.get("cancel_only", False))
        item_index = int(p.get("item_index", 0))
        end = time.time() + timeout

        if not MainCity(ui).ensure():
            return TaskResult.fail("回不到主城")
        # 2026-11-20 审计 CRITICAL：确认框里「花费 💎-154」被当成「商人倒给你钻」，
        # 全流程没有任何主城钻石前后差核对 —— 符号判错就是静默真花钻还报「已购买」。
        # 现在进页前先记一次主城钻石（读两帧一致才采纳），成交后再读一次对比。
        d0 = self.diamonds_stable(ui, "merchant_d0") if not cancel_only else None
        if d0 is None and not cancel_only:
            log.info("  公会商人：进页前读不到主城钻石（读数缺证），成交后只能按「有没有证据」判")
        elif d0 is not None:
            log.info(f"  公会商人：进页前主城钻石 {d0}")
        page = MerchantPage(ui)
        if not page.enter():
            return TaskResult.skip("进不去公会商人")

        im = ui.screen("merchant")
        disc, score = page.discount(im)
        if disc is None:
            log.warn(f"  公会商人：折扣数字识别失败（{score:.2f}），不拍板、不购买")
            page.back_to_guild()
            MainCity(ui).ensure()
            return TaskResult.skip("折扣数字识别失败（置信度低）")
        log.info(f"  公会商人：当前折扣 -{disc}（识别置信度 {score:.2f}）")

        # 负折扣越大越赚：即使已过 -100 也继续压，直到界面次数上限或连续两次不再变化
        last, stall, n = disc, 0, 0
        while n < max_bargains and time.time() < end:
            if not page.bargain():
                # 底部不是金色「议价」（本阶段已是灰「已购买/议价上限」），再点也是空转
                break
            im = ui.screen("merchant_bargain")
            val, sc = page.discount(im)
            if val is None:
                # 2026-11-19 假成功审计（audit2 TOP10）：以前先 n += 1 再读折扣，
                # 读不出时这一轮已经计进 bargains。现在读到了才计。
                log.warn(f"  公会商人：第 {n + 1} 次点「议价」后折扣读不出（{sc:.2f}），"
                         f"停止议价（这次不计入议价次数）")
                break
            n += 1
            can_push = "还能继续压" if n < max_bargains else "已到次数上限"
            log.info(f"  公会商人：第 {n} 次议价 → 折扣 -{val}（{sc:.2f}），{can_push}")
            if val == last:
                stall += 1
            else:
                stall, last = 0, val
            disc = val
            if stall >= 2:
                log.warn("  公会商人：连续两次议价折扣没变（可能到当日议价上限）")
                break

        if disc < need:
            log.info(f"  公会商人：折扣 -{disc} 未到 -{need}，本轮不购买")
            page.back_to_guild()
            MainCity(ui).ensure()
            return TaskResult(True, f"公会商人：折扣 -{disc} 未达 -{need}，未购买",
                              {"discount": -disc, "bargains": n, "bought": False,
                               "noop_ok": True})

        # 达标：选商品 → 购买按钮 → 确认框
        page.select_item(item_index)
        state = page.buy(cancel_only=cancel_only)
        ok = state == "bought"
        said = {"bought": "已购买", "sold_out": "今天这档已买过",
                "cancelled": "已取消（不消费钻石）",
                "no_confirm": "没弹出确认框",
                "no_button": "底部购买按钮不可用"}.get(state, state)
        log.info(f"  公会商人：折扣 -{disc}（已过 -{need} 阈值），购买结果：{said}")
        page.back_to_guild()
        MainCity(ui).ensure()
        d1 = self.diamonds_stable(ui, "merchant_d1")
        stats = {"discount": -disc, "bargains": n, "bought": ok, "state": state,
                 "diamonds_before": d0, "diamonds_after": d1}
        if ok and d0 is not None and d1 is not None and d1 < d0:
            # 成交却把钻石花掉了 = 那次「倒给你的钻」判断是错的（或当期文案改了）
            log.warn(f"  公会商人成交扣了钻石：{d0} → {d1}（少了 {d0 - d1}），"
                     f"说明「花费 💎-N 是收入」的判断不成立，请核对")
            return TaskResult.fail(
                f"公会商人：{said}，但主城钻石 {d0}→{d1} 少了 {d0 - d1}，怀疑真花钻了", stats)
        if ok and d0 is not None and d1 is not None:
            log.info(f"  公会商人：成交后主城钻石 {d0}→{d1}（没少），与「倒给你钻」的判断一致")
        if state == "no_confirm":
            # 2026-11-09 假成功审计：点了购买却连确认框都没弹 → 脚本没点通，不能报 OK
            return TaskResult.fail(f"公会商人：折扣 -{disc}，{said}（按钮/确认框都没接通）", stats)
        if state == "no_button":
            # 底部没有金钮 = 今天这档已买过（sold_out 走的是另一分支），属真状态
            log.info(f"  公会商人：折扣 -{disc}，{said}（真状态，不是脚本问题）")
        return TaskResult(True, f"公会商人：折扣 -{disc}，{said}", stats)
