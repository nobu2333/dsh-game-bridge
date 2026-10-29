"""dsh-game-core —— dsh-game-bridge 的本地引擎。

职责边界：只做「眼睛」（抓屏 / OCR / 帧差分）与将来的「手 / 小脑」，
不认识模型、不认识 DSH、不读玩家隐私数据。通信走 stdio JSON，一行一帧。
"""

__version__ = "0.0.1"
