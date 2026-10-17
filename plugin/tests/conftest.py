"""pytest 会话隔离：测试流量不得写入生产日志（21 号日志数据卫生）。

背景：部分测试直接调 `HANDLERS[...]`（未自行 mock 日志路径），此前会把记录写进
`logs/usage_log.jsonl`。2026-09-29 实测：全量跑一次泄漏 ~110 条，7 次运行 = 770 条，
占当日日志 89%——观测期取数前必须先隔离。

为什么不能只设 env：`plugin/__init__.py` 顶层 `from .tools import HANDLERS` 会连锁导入
`plugin.config`，而 pytest 导入 `plugin.tests.*` 前必先导入父包 `plugin`——conftest 的
模块体永远晚于 config 加载，此时 LOG_DIR 已定。故此处**显式覆盖模块属性**
（log_usage / log_gap / trajectory 在调用时读模块全局，覆盖即生效）。
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="i2bkn_test_logs_"))
# 供「导入期之后才读 env」的路径（如子进程/脚本重载）使用
os.environ["LOG_DIR"] = str(_TMP)

from plugin import supplement as _supplement  # noqa: E402
from plugin import usage_log as _usage_log  # noqa: E402
from plugin import trajectory as _trajectory  # noqa: E402
from plugin import loaded_version as _loaded_version  # noqa: E402

# patch 的是**逻辑基名**：实际写入由 rotate_day_file 按日期派生到 _TMP 下
_usage_log.USAGE_LOG = _TMP / "usage_log.jsonl"
_supplement.GAP_LOG_PATH = _TMP / "gap_log.jsonl"
# 批 U-1（2026-10-12）：轨迹同理——带 task_id 的测试（test_u0_channel / test_usage_log）
# 会把事件写进生产 logs/trajectories/；演练抓到后补隔离（与上两处同一手法）。
_trajectory.TRAJ_LOG = _TMP / "trajectories" / "trajectory.jsonl"
# 批 V-1 × U-2（2026-10-12）：服务自证同理——test_resolver 会真调 reload()，
# 其自证会写进生产 logs/.loaded_version.json（检查脚本据此假报"一致"）；同法补隔离。
_loaded_version.LOADED_VERSION_FILE = _TMP / ".loaded_version.json"
