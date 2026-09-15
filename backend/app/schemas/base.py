# 응답 JSON 키를 camelCase 로 내리기 위한 공통 베이스 (루트 CLAUDE.md API 규약)

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)