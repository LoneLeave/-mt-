"""mtbot —— 《我叫MT：崛起》自动化框架。

分层（与 OAS 的思路一致）：
  device / emulator  →  只负责 adb、模拟器，不认识游戏
  vision             →  只负责像素判读与画面状态分类，不认识 adb
  ui / pages         →  负责页面识别与导航，不写业务目标
  tasks              →  业务目标（每日、奖励、战斗），只调用 pages/ui
  scheduler / run    →  配置驱动的调度与命令行入口
"""
__version__ = "2.0.0"
