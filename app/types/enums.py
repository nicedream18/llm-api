"""Response codes and enums."""
from enum import Enum


class ResponseCode(str, Enum):
    SUCCESS = ("0000", "\u6210\u529f")
    UN_ERROR = ("0001", "\u672a\u77e5\u5931\u8d25")
    ILLEGAL_PARAMETER = ("0002", "\u975e\u6cd5\u53c2\u6570")
    NOT_FOUND = ("0003", "\u8d44\u6e90\u4e0d\u5b58\u5728")
    CHANNEL_UNAVAILABLE = ("0004", "\u65e0\u53ef\u7528\u6e20\u9053")
    ADAPTOR_NOT_FOUND = ("0005", "\u65e0\u5bf9\u5e94\u6e20\u9053\u9002\u914d\u5668")
    SECURITY_BLOCKED = ("0006", "\u8bf7\u6c42\u88ab\u5b89\u5168\u7b56\u7565\u62e6\u622a")
    QUOTA_EXCEEDED = ("0007", "\u914d\u989d\u5df2\u7528\u5c3d")
    UNAUTHORIZED = ("0008", "\u672a\u6388\u6743\u8bbf\u95ee")
    REMOTE_ERROR = ("0009", "\u4e0a\u6e38\u670d\u52a1\u8c03\u7528\u5931\u8d25")

    def __new__(cls, code, info):
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj.code = code
        obj.info = info
        return obj


class ChannelType(str, Enum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    CLAUDE = "claude"
    GEMINI = "gemini"
    QWEN = "qwen"
    ZHIPU = "zhipu"
    MOONSHOT = "moonshot"
    DOUBAO = "doubao"
    OLLAMA = "ollama"
    CUSTOM = "custom"

    @classmethod
    def from_value(cls, value):
        for t in cls:
            if t.value == value:
                return t
        return cls.CUSTOM


CHANNEL_DEFAULTS = {
    ChannelType.OPENAI: "https://api.openai.com/v1",
    ChannelType.DEEPSEEK: "https://api.deepseek.com/v1",
    ChannelType.CLAUDE: "https://api.anthropic.com",
    ChannelType.GEMINI: "https://generativelanguage.googleapis.com/v1beta",
    ChannelType.QWEN: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ChannelType.ZHIPU: "https://open.bigmodel.cn/api/paas/v4",
    ChannelType.MOONSHOT: "https://api.moonshot.cn/v1",
    ChannelType.DOUBAO: "https://ark.cn-beijing.volces.com/api/v3",
    ChannelType.OLLAMA: "http://localhost:11434/v1",
    ChannelType.CUSTOM: "",
}


class ProtocolFormat(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    RESPONSES = "responses"


class RiskLevel:
    CLEAN = ("Clean", 0)
    INFO = ("Info", 1)
    LOW = ("Low", 5)
    MEDIUM = ("Medium", 15)
    HIGH = ("High", 40)
    CRITICAL = ("Critical", 100)

    @staticmethod
    def from_score(score):
        if score >= 100:
            return "Critical"
        if score >= 40:
            return "High"
        if score >= 15:
            return "Medium"
        if score >= 5:
            return "Low"
        if score >= 1:
            return "Info"
        return "Clean"

    @staticmethod
    def threshold(label):
        mapping = {
            "Clean": 0, "Info": 1, "Low": 5,
            "Medium": 15, "High": 40, "Critical": 100,
        }
        return mapping.get(label, 0)


SEVERITY_SCORES = {
    "info": 1,
    "low": 5,
    "medium": 15,
    "high": 40,
    "critical": 100,
}
