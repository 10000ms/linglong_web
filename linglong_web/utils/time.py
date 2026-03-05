from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

ShangHaiTZ = ZoneInfo('Asia/Shanghai')
NewYorkTZ = ZoneInfo('America/New_York')
ServerTargetTZ = ShangHaiTZ


def to_server_tz_iso(dt: Optional[datetime], target_tz: Optional[ZoneInfo] = None) -> Optional[str]:
	"""将时间统一转换为服务端目标时区并输出 ISO 字符串 / Convert datetime to server target TZ ISO string."""
	if dt is None:
		return None
	tz = target_tz or ServerTargetTZ
	normalized = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
	return normalized.astimezone(tz).isoformat()
