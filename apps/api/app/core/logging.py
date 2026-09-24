import json, logging, re
class SensitiveQueryFilter(logging.Filter):
    def filter(self,record):
        if record.args:
            record.args=tuple(re.sub(r"([?&]token=)[^&\s\"]+",r"\1[REDACTED]",x) if isinstance(x,str) else x for x in record.args) if isinstance(record.args,tuple) else record.args
        record.msg=re.sub(r"([?&]token=)[^&\s\"]+",r"\1[REDACTED]",str(record.msg));return True
from datetime import datetime, timezone
class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname, "logger": record.name, "message": record.getMessage()}, ensure_ascii=False)
def configure_logging(level="INFO"):
    handler = logging.StreamHandler(); handler.setFormatter(JsonFormatter());handler.addFilter(SensitiveQueryFilter())
    root = logging.getLogger(); root.handlers = [handler]; root.setLevel(level)
