"""Safe repair guidance shared by all Agent report transports."""
import hashlib
import json


def schema_id(schema):
    return 'report-'+hashlib.sha256(json.dumps(schema,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]


def validation_issue(error):
    text=str(error)
    kinds={
        'Invalid participation fact':('participation','参与状态格式不符，请区分参与状态与主网开挖状态。',['open','closed','unknown']),
        'Invalid market fact':('market','市场状态只能使用已定义的值。',['yes','no','unknown']),
        'Invalid skill fact':('skill_level','技能要求格式不符。',['beginner','intermediate','advanced','unknown']),
        'Invalid OS fact':('operating_system','操作系统格式不符，请使用规定的名称或未知值。',['windows','linux','darwin','unknown']),
        'Agent report is too large':('size','报告过长，请精简后补交，无需重新检索。',[]),
    }
    code,message,allowed=kinds.get(text,('report_format','报告格式或来源引用未通过校验，请按领取时的格式修正后补交。',[]))
    return {'code':code,'message':message,'allowed_values':allowed}


class ProviderReportError(ValueError):
    def __init__(self,message,usage=None,report_text=None):
        super().__init__(message);self.usage=usage;self.report_text=report_text
